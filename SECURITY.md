# Security

This application is for a single user on a trusted local machine. It has no
multi-user authentication and must not be exposed through a public reverse proxy.

Please use this repository's private vulnerability reporting feature for security
reports. Do not publish secrets, task archives, local configuration, logs or
backups in public issues. If private reporting is unavailable, open a minimal
issue requesting a private reporting channel without including exploit details
or personal data.

Configuration, integration allowlists and imported task boards are trusted local
inputs. Imported Skills are indexed, never executed by the workbench. Review
Skill instructions yourself before asking an AI to execute them.
