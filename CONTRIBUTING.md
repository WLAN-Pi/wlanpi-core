# Contribution Guidelines

For the greatest chance of helpful responses, please observe the following guidelines.

## Repository Structure

We maintain two primary branches:
- `main`: considered as the stable / release branch for wlanpi-core.
- `dev`: development branch where all contributions are integrated, made stable, and then PR'd into main.

## Types of Contributors

### Internal Contributors (with repo write access)

1. Create feature branches from dev:
   ```bash
   git checkout dev
   git pull origin dev
   git checkout -b feature/descriptive-name
   ```
2. Make changes and push to your feature branch
3. Create PR from feature branch to dev

### External Contributors (without write access)

1. Fork the repository
2. Work in your fork's dev branch
3. Create PR from your fork's dev to this repository's dev branch

## Questions

The GitHub issue tracker is for *bug reports* and *feature requests*. Please do
not use it to ask questions about usage. These questions should
instead be directed through other channels.

## Good Bug Reports

Please be aware of the following things when filing bug reports:

1. Avoid raising duplicate issues. *Please* use the GitHub issue search feature
   to check whether your bug report or feature request has been mentioned in
   the past. Duplicate bug reports and feature requests are a huge maintenance
   burden on the project maintainers. If it is clear from your report that you 
   would have struggled to find the original, that's ok, but if searching for 
   a selection of words in your issue title would have found the duplicate
   then the issue will likely be closed.

2. When filing bug reports about exceptions or tracebacks, please include the
   *complete* traceback. Partial tracebacks, or just the exception text, are
   not helpful. Issues that do not contain complete tracebacks may be closed
   without warning.

3. Make sure you provide a suitable amount of information to work with. This
   means you should provide:

   - Guidance on **how to reproduce the issue**. Ideally, this should be a
     *small* code sample that can be run immediately by the maintainers.
     Failing that, let us know what you're doing, how often it happens, what
     environment you're using, etc. Be thorough: it prevents us needing to ask
     further questions.
   - Tell us **what you expected to happen**. When we run your example code,
     what are we expecting to happen? What does "success" look like for your
     code?
   - Tell us **what actually happens**. It's not helpful for you to say "it
     doesn't work" or "it fails". Tell us *how* it fails: do you get an
     exception? How was the actual result different from your expected result?
   - Tell us **what version you're using**, and
     **how you installed it**. Different versions behave
     differently and have different bugs.

If you do not provide all of these things, it can take us much longer to
fix your problem. If we ask you to clarify these and you never respond, we
will close your issue without fixing it.

## Code Contributions

Some tips to _consider_.

### Before You Start Coding

To increase the chances of Pull Request (PR) approval, first, talk to one of the core [WLAN Pi](https://github.com/WLAN-Pi/) [team members](https://github.com/orgs/WLAN-Pi/people) or open an issue so we can discuss them. It's also a great idea to review the [organization contributing guidelines](https://github.com/WLAN-Pi/.github/blob/main/docs/contributing.md).

Aligning your ideas with the project team (before doing the work) will save everybody's time.

### Commit Messages

Follow the conventional commits format:

```
feat: new feature
fix: bug fix
docs: documentation changes
refactor: code restructuring
test: adding tests
```

### Development Environment

Use whatever tooling you want for developing.

Need help? Consider using PyCharm or Visual Studio Code (VSC) with the official Python and Pylance extensions from Microsoft.

### Pull Requests

Before submitting a PR perform the following:

1. Lint your code with `tox -e lint` and make sure it passes.

2. Format your code with `tox -e format`.

3. Create a test that validates your changes. This test should go in `/tests`.

4. Ensure all tests pass by running `tox`.

These steps are done from the root directory of the repo. 

Depending on how you're testing your changes, you may need to first setup and activate the virtualenv.

Failure to do so means it will take longer to test, validate, and merge your PR into the repo.

CI/CD workflows will also fail if tox fails.

## Code Review Process

1. All changes require at least one review
2. Address any feedback from reviewers
3. CI checks must pass
4. Maintainers will handle the final merge

## Release Process

Maintainers handle releases by:

1. Merging `dev` into `main`
2. Creating a new version tag
3. Publishing release notes