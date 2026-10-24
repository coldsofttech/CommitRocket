# Security Policy

## Supported versions

Security fixes are made for the latest released version. Please upgrade before reporting
a problem that may already be fixed.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**, or go directly to
   <https://github.com/coldsofttech/CommitRocket/security/advisories/new>.

Include what you found, the steps to reproduce it, the CommitRocket, Git and git-lfs
versions, your operating system, and what you think the impact is. Please leave out real
credentials and private repository contents.

You can expect an acknowledgement within about 7 days. After that, we will keep you
updated on the investigation and agree on a date for the fix and its disclosure with you.
Credit is given in the release notes if you would like it.

## What is in scope

CommitRocket runs Git commands on your repository and can send an optional webhook
notification, so reports about the following are especially welcome:

- Commands or paths from repository content, config files or options being run or
  interpreted unsafely.
- Files being committed, pushed or written outside what the options and filters allow.
- Secrets, such as webhook addresses, appearing in reports or logs.
- Unsafe handling of the config file, the report file or the log file.

Problems in Git, Git LFS, your Git host or other dependencies should be reported to those
projects.
