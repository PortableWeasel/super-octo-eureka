# Repository Guidelines

This project provides a CLI utility for mirroring remote Git repositories into a GitHub-like folder structure and keeping Gitolite configuration in sync.

## Implementation
- The tool is implemented as Python modules inside the `git_mirror` package.
- Split functionality across multiple files within the module to keep components focused and maintainable.

## Development Practices
- When adding or modifying command-line features, include an example demonstrating its usage.
- Update the Bash completion support to reflect any CLI changes.
- Store frequently required fields via the configuration command and config file rather than hard-coding them.

Run tests with `pytest` after making changes.
