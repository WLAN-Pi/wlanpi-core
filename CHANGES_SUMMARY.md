# Network Namespaces Hardening and Robustness Improvements

## Issue Summary

The namespaces code had several critical deficiencies that could block wlanpi-core functionality and prevent other modes (e.g., hotspot) from starting:

1. **Configuration file handling**: The namespaces code did not handle incorrectly formatted configuration files gracefully
2. **Blocking startup**: The namespaces code ran as a blocking part of wlanpi-core startup, and if it failed, core failed to start
3. **Mode conflicts**: The namespaces code would always attempt to configure adapters in any mode, conflicting with other modes when not in classic mode
4. **API error handling**: The API returned a 500 failure if any namespaces were inaccessible and did not attempt to return other found configurations
5. **Autostart app fragility**: The launch and shutdown of the autostart_app was fragile with improper detection of run state and subsequent return of status
6. **Process killing bug**: Shutting down a namespace could kill processes in the root space if they matched a process name in the namespace (e.g., if Orb was required for autostart in a namespace but not running when the namespace was deleted, orb running in root via the installed service would be forcefully killed)

## Requirements

- Ensure wlanpi-core can start regardless of the state of the namespaces code
- Make namespaces code robust against configuration errors
- Restrict namespaces code to running only in classic mode
- Harden namespaces code to gracefully fall back to defaults when configs are misconfigured or missing

## Changes Implemented

### App (`wlanpi_core/app.py`)

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

### API (`wlanpi_core/api/api_v1/endpoints/network_config_api.py`)

1. **422 status code for malformed configurations**
   - Added `ConfigMalformedError` exception handling to both `get_config_by_id` and `activate_config` endpoints
   - Returns HTTP 422 (Unprocessable Entity) with descriptive error message when configuration is malformed
   - Provides consistent error handling across configuration-related endpoints

2. **Status API protection**
   - The `/status` API endpoint now has protection to ensure that a single corrupt or inaccessible namespace does not block the status from returning
   - Individual namespace errors are caught and logged, with error indicators added to the response for that namespace
   - Other namespaces continue to be processed and returned even if one fails

### Network Namespace Service (`wlanpi_core/services/network_namespace_service.py`)

1. **Pre-validation routine**
   - Added comprehensive `_validate_config()` method that validates configuration files before any state changes
   - Validates all required fields, types, and security configurations
   - Returns detailed error messages describing validation failures
   - Prevents activation of invalid configurations

2. **Interface availability checking**
   - Checks availability of interfaces prior to executing a configuration file
   - Only configurations with available interfaces will be executed
   - If a configuration specifies wlan0 and wlan1 but wlan1 is not available, only the wlan0 configuration will be executed
   - Previously, wlan1 would be attempted and fail (however the failure was not critical and did not affect wider functionality)
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

### Network Config (`wlanpi_core/utils/network_config.py`)

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

### Models (`wlanpi_core/models/network_config_errors.py`)

1. **New exception types**
   - Added `ConfigMalformedError` exception class with `message` and optional `cfg_id` attributes
   - Extends existing `ConfigActiveError` for better error categorization

## Testing Recommendations

1. **Startup resilience**
   - Test wlanpi-core startup with malformed configuration files
   - Test startup in non-classic modes (hotspot, etc.)
   - Verify core starts successfully even if namespace initialization fails

2. **Configuration validation**
   - Test activation of malformed configurations (should return 422)
   - Test activation with missing interfaces (should skip unavailable interfaces)
   - Test with empty configuration files

3. **Mode restrictions**
   - Test namespace operations in classic mode (should work)
   - Test namespace operations in other modes (should be skipped)

4. **Status API**
   - Test status API with corrupted namespaces
   - Verify other namespaces are still returned when one fails

5. **Process management**
   - Test autostart app in namespace
   - Test stopping namespace with app running
   - Verify root namespace processes are not killed when stopping namespace apps

6. **Rollback**
   - Test activation failure scenarios
   - Verify only activated configs are rolled back

## Files Changed

- `wlanpi_core/app.py` - Asynchronous initialization, classic mode check, exception handling
- `wlanpi_core/api/api_v1/endpoints/network_config_api.py` - 422 error handling, status protection
- `wlanpi_core/services/network_namespace_service.py` - Validation, async monitoring, interface checking, improved app management
- `wlanpi_core/utils/network_config.py` - Fallback configs, malformed detection, rollback logic
- `wlanpi_core/models/network_config_errors.py` - New exception types

## Notes

- The default namespace change from "root" to `None` is a breaking change for any code that explicitly checks for "root" namespace strings, but this should be minimal as the codebase uses `None` consistently now.
