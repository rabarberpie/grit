# grit
grit is a tool for managing many git repositories in a single project; it is an alternative to repo.

It is designed with below principles:
* Stay close to the git concepts and terminologies, including option names.
* Layered settings, making it easy to override a specific setting by overlaying.
* Use JSON as format for settings files, for easy parsing, as well as easy manual editing.

# Manifests
Manifest files are the core settings files and have below sections:
* Repositories: Contain the list of repositories that are included by the manifest. Optionally, may also include parameters/options which override the profile settings (see below).

* Profiles: A profile contains all required settings/parameters/options to interact with the remote repository (using git). Typically, many repositories share the same settings, which is achieved by using the same profile. Optionally, one profile can be appointed as "default", which will then be used for all repositories which doesn't explicitely reference a specific profile.
Additionally (and optionally), one profile can be appointed as "global". If a profile is missing a setting, the global profile (if defined) is checked for the setting (as a last step).
This can be used to easily share settings across all profiles, such as clone depth or branch name.

Thus, the priority order of any setting is:
1. The repository setting.
2. The referenced profile setting (or default)
3. The global profile setting.

# Configuration
A specific configuration consists of layering one or many manifests on top of each other, where upper manifests override settings from lower manifests. The resulting manifest is stored as an "active manifest". Most gitre commands are performed against this manifest.
Optionally, as a first step, it can retrieve additional manifest files from other locations (e.g. using git clone, ftp, etc.).

# Data Extension
It is possible to add arbritarily json key/values as long as they start with "x-". grit will ignore all these keys. This can be used to store additional meta-data about the repositories, such as code license information, which is parsed by other tools.

# Generic commands
Generic commands are git commands that are transparently executed on all target repositories. For each repository, the result is printed as returned by git, prefixed with header lines that shows which repository the result is related to.
Essentially, grit here acts like an iterator of multiple repositories, executing the same git command.

Syntax:
grit <grit-options> <git-command> <git-command-parameters>

grit-options are:
 -g<groups>      comma-separated list of group (optional)
 -j<n>           n is the number of parallel jobs being executed (default: 1)
 --verbose, -v   add some more verbose printing (to grit; not to the git command!)

git-command is one of:
remote, rebase, fetch, pull, push, merge, branch, status, stash, tag

git-command-parameters are passed transparently to the specied git command.

Examples:
grit status
- Execute "git status" on all respositories in the active manifest.
grit -j4 -gg1,g2 status -s
- Execute "git status -s" on all respositories belonging to either group "g1" or "g2". Perform this operation using 4 parallel processes.

# Clone command
Cloning repositories in the active manifest is not a generic command, but have grit-specific logic. This is required since each repository has its own individual settings, as specified by the active manifest.

Syntax:
grit <grit-options> clone

grit-options are:
 -g<groups>      comma-separated list of group (optional)
 -j<n>           n is the number of parallel jobs being executed (default: 1)
 --verbose, -v   add some more verbose printing


Examples:
grit clone
- Clone all repositories in the active manifest.
grit -j4 -gg1,g2 clone
- Clone all respositories belonging to either group "g1" or "g2". Perform this operation using 4 parallel processes.

