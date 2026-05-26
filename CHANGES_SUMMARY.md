## Type of change 

* [x] Bug fix (non-breaking change that fixes something)
* [ ] Documentation update (readme, changelog, man page, etc.)
* [x] New feature (non-breaking change adding functionality)
* [x] Breaking change (fix or feature changing existing functionality)
* [x] Code quality improvement (refactor, performance improvements)
* [ ] Other (please specify):

## Breaking change

<!-- *Does this Pull Request introduce a breaking change?* -->

**Yes, one breaking change:**

- **What functionality breaks?**
  - Code that explicitly checks for the string "root" as a namespace identifier will break. The root namespace is now represented by `None` instead of the string "root".

- **Why does it break?**
  - Changed the default namespace representation from the string "root" to `None` to avoid confusion and prevent users from creating a namespace named "root" which would cause conflicts.

- **How should it be migrated?**
  - Any code checking `namespace == "root"` should be changed to `namespace is None` or `namespace is None or namespace == "root"` for backward compatibility during transition.

- **Are there any backward-compatible alternatives?**
  - The codebase has been updated to use `None` consistently throughout. External code or scripts that check for "root" namespace will need to be updated. This should be minimal impact as the codebase itself has been fully migrated.

## Proposed change

<!-- *Please describe the purpose of this change, the problem it solves, and why the change is necessary. Including code snippets or links to related documentation when applicable will assist approval.* -->

This PR hardens the network namespaces functionality to make wlanpi-core more robust and prevent namespace-related failures from blocking core startup or interfering with other modes.

### Problems Solved

1. **Configuration file handling**: The namespaces code did not handle incorrectly formatted configuration files gracefully
2. **Blocking startup**: The namespaces code ran as a blocking part of wlanpi-core startup, and if it failed, core failed to start
3. **Mode conflicts**: The namespaces code would always attempt to configure adapters in any mode, conflicting with other modes when not in classic mode
4. **API error handling**: The API returned a 500 failure if any namespaces were inaccessible and did not attempt to return other found configurations
5. **Autostart app fragility**: The launch and shutdown of the autostart_app was fragile with improper detection of run state and subsequent return of status
6. **Process killing bug**: Shutting down a namespace could kill processes in the root space if they matched a process name in the namespace (e.g., if Orb was required for autostart in a namespace but not running when the namespace was deleted, orb running in root via the installed service would be forcefully killed)

### Implementation Details

#### App (`wlanpi_core/app.py`)

1. **Asynchronous namespace initialization**
   - Initialization of network namespace is now an asynchronous function called with `await` in `initialize_components`
   - Added threading support and moved connection initialization to its own thread
   - Introduced an asynchronous connection monitor which runs in the background, allowing core to initialize quickly while Wi-Fi connections are handled by the background process
   - All calls now return "provisioned" as soon as they are setup and will enter the "connected" state later if and when connection completes

2. **Classic mode restriction**
   - Initialization of network namespace only allowed when in classic mode
   - Checks `/etc/wlanpi-state` contains the value "classic" before proceeding
   - If not in classic mode, namespace operations are skipped with appropriate logging

3. **Enhanced exception handling**
   - Added comprehensive exception handling and logging to initialization code
   - Network namespace initialization failures are non-blocking and do not prevent core startup
   - Malformed current configuration files are detected and fallback to default is performed
   - All namespace initialization errors are logged but marked as non-critical

4. **Default config fallback**
   - When current config is malformed or missing, gracefully falls back to default configuration
   - Ensures default config exists during system readiness check

#### API (`wlanpi_core/api/api_v1/endpoints/network_config_api.py`)

1. **422 status code for malformed configurations**
   - Added `ConfigMalformedError` exception handling to both `get_config_by_id` and `activate_config` endpoints
   - Returns HTTP 422 (Unprocessable Entity) with descriptive error message when configuration is malformed
   - Provides consistent error handling across configuration-related endpoints

2. **Status API protection**
   - The `/status` API endpoint now has protection to ensure that a single corrupt or inaccessible namespace does not block the status from returning
   - Individual namespace errors are caught and logged, with error indicators added to the response for that namespace
   - Other namespaces continue to be processed and returned even if one fails

#### Network Namespace Service (`wlanpi_core/services/network_namespace_service.py`)

1. **Pre-validation routine**
   - Added comprehensive `_validate_config()` method that validates configuration files before any state changes
   - Validates all required fields, types, and security configurations
   - Returns detailed error messages describing validation failures
   - Prevents activation of invalid configurations

2. **Interface availability checking**
   - Checks availability of interfaces prior to executing a configuration file
   - Only configurations with available interfaces will be executed
   - If a configuration specifies wlan0 and wlan1 but wlan1 is not available, only the wlan0 configuration will be executed
   - Returns "provisioned" status for valid configs with unavailable interfaces, allowing other interfaces to still be activated

3. **Default namespace change**
   - Changed the default namespace from "root" to `None` to avoid the possibility of a user calling their namespace "root"
   - This prevents confusion in the namespaces code and avoids broken outcomes
   - All namespace operations now use `None` to represent the root namespace

4. **Asynchronous connection monitoring**
   - Implemented background connection monitoring using threading
   - Connection setup returns immediately with "provisioned" status
   - Background monitor handles:
     - Connection state polling
     - DHCP client startup when connection completes
     - Default route setup
     - Autostart app launching
   - Monitor can be stopped gracefully when namespace is deactivated

5. **Enhanced exception handling and logging**
   - Added extensive exception handling throughout the service
   - Improved logging at all critical points
   - Errors are logged with appropriate context but do not block operations unnecessarily

6. **Improved autostart app management**
   - Enhanced `start_app_in_namespace()` with better process verification
   - Improved `stop_app_in_namespace()` with namespace-aware process identification
   - Uses PID files with JSON format storing PID, app_id, and app_command
   - Verifies processes are actually in the target namespace before killing
   - Prevents killing processes in root namespace when stopping namespace apps
   - Uses `ip netns identify` and `ip netns pids` to verify process location

7. **Rollback on activation failure**
   - When activation fails, only successfully activated configs are rolled back
   - Tracks which configs were actually activated before attempting rollback
   - Prevents partial state issues

#### Network Config (`wlanpi_core/utils/network_config.py`)

1. **Programmatic fallback namespace configuration**
   - Created `get_default_config()` function that returns a programmatic fallback namespace configuration
   - Used when default config is not present or valid in the filesystem
   - Provides a safe default configuration structure

2. **Malformed file detection and annotation**
   - When listing stored configuration files, identifies those which are malformed
   - Annotates displayed filenames of incorrect files with "(empty)" or "(malformed)"
   - Detects malformed JSON and only returns configuration files which are parsable JSON
   - Validates configuration structure (must have 'id' field)

3. **Active configuration validation**
   - Detects if the current active configuration file is still valid JSON
   - Catches breaking changes to the file once it is activated
   - This will catch a change to an active config which then breaks on reboot
   - Automatically reverts to "default" when active config becomes invalid

4. **Correct rollback on activation failure**
   - When activation of a configuration fails to complete, correctly rolls back only the successfully activated configs
   - Tracks which configs were activated before attempting rollback
   - Prevents leaving system in partial state

5. **Enhanced status endpoint**
   - Status endpoint now handles individual namespace errors gracefully
   - Continues processing other namespaces even if one fails
   - Returns error indicators for failed namespaces while still returning successful ones

#### Models (`wlanpi_core/models/network_config_errors.py`)

1. **New exception types**
   - Added `ConfigMalformedError` exception class with `message` and optional `cfg_id` attributes
   - Extends existing `ConfigActiveError` for better error categorization

### Files Changed

- `wlanpi_core/app.py` - Asynchronous initialization, classic mode check, exception handling
- `wlanpi_core/api/api_v1/endpoints/network_config_api.py` - 422 error handling, status protection
- `wlanpi_core/services/network_namespace_service.py` - Validation, async monitoring, interface checking, improved app management
- `wlanpi_core/utils/network_config.py` - Fallback configs, malformed detection, rollback logic
- `wlanpi_core/models/network_config_errors.py` - New exception types

> **Note:** This PR includes a merge from `upstream/dev` to stay current with the latest changes. The diff may include changes from PR #108 which are already merged upstream. The new feature commits in this PR are listed above.

## Testing

<!-- *Please explain how you tested this change manually, and if applicable, what new tests you added.* -->

- [ ] Did you add new automated tests? If yes, explain which edge cases are covered.
  - No new automated tests were added in this PR, but comprehensive manual testing was performed.

- [ ] Does this change affect any existing tests? If so, how did you adjust them?
  - Existing tests should continue to work, but may need updates for the namespace default change from "root" to `None`.

- [x] Please provide test run results or screenshots if applicable.

### Manual Testing Performed

1. **Startup resilience**
   - Tested wlanpi-core startup with malformed configuration files
   - Tested startup in non-classic modes (hotspot, etc.)
   - Verified core starts successfully even if namespace initialization fails

2. **Configuration validation**
   - Tested activation of malformed configurations (returns 422 as expected)
   - Tested activation with missing interfaces (skips unavailable interfaces as expected)
   - Tested with empty configuration files

3. **Mode restrictions**
   - Tested namespace operations in classic mode (works as expected)
   - Tested namespace operations in other modes (skipped as expected)

4. **Status API**
   - Tested status API with corrupted namespaces
   - Verified other namespaces are still returned when one fails

5. **Process management**
   - Tested autostart app in namespace
   - Tested stopping namespace with app running
   - Verified root namespace processes are not killed when stopping namespace apps

6. **Rollback**
   - Tested activation failure scenarios
   - Verified only activated configs are rolled back

## LLM/AI usage

<!-- *Please disclose any use of LLMs or AI coding assistants in creating this PR.* -->

- [ ] I used an LLM or AI coding assistant for this PR
- If yes, please describe:
  - Which tool(s) and model(s) were used (e.g., Gemini 2.5 Flash, Claude 4.5 Sonnet, Copilot GPT-4, ChatGPT GPT-5)?
  - What portions of the code and PR were assisted?
  - Have you reviewed and tested all generated code for correctness?

## Checklist

<!-- No PR without a related GH issue! Conversations about your PR efforts in other channels such as electronic mail, social media, morse code, homing pigeon, or slack are great starting points, but **do not count** for this requirement. --> 

* [x] I have read the [contribution guidelines and policies](https://github.com/WLAN-Pi/.github/blob/main/docs/contributing.md)
* [x] I have targeted this PR against the correct git branch (this can vary depending on the default branch of the repo)
* [ ] I ran the test suite and verified it succeeded
* [ ] I linked a GitHub issue to this PR (in the next section). 
* [ ] I have updated the changelog (if applicable)
* [ ] I have added or updated the documentation (if applicable)

## Related Issues/PRs

<!-- *Pick at least one. Delete the other lines.* -->

- This PR fixes/closes issue #
- This PR is related to issue #
- This PR depends on/blocks PR #
