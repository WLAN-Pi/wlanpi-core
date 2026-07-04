# Contributing

See the [WLAN Pi developer documentation](https://github.com/WLAN-Pi/developers) for contribution guidelines, workflow, branch naming, commit standards, and style guides.

## wlanpi-core Specific

### Pull Requests

Before submitting a PR:

1. Lint your code with `tox -e lint` and make sure it passes.
2. Format your code with `tox -e format`.
3. Create a test that validates your changes in `/tests`.
4. Ensure all tests pass by running `tox`.

These steps are run from the root of the repo. CI/CD will also run `tox` and fail if it does not pass.

### Code Review

1. All changes require at least one review.
2. Address any feedback from reviewers.
3. CI checks must pass.
4. Maintainers will handle the final merge.
