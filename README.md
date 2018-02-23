# grit
grit is a tool for managing many git repositories in a single project; it is an alternative to repo.

It is designed with below principles:
* Stay close to the git concepts and terminologies, including option names.
* Layered settings, making it easy to override a specific setting by overlaying.
* Use JSON as format for settings files, for easy parsing, as well as easy manual editing.

# Manifests
Manifest files are the core settings files and have below sections:
* Repositories: Contain the list of repositories that are included by the manifest. Optionally, may also include parameters/options which override the profile settings (see below).

* Profiles: A profile contains all required settings/parameters/options to interact with the remote repository (using git). Typically, many repositories share the same settings; by placing these in a shared profile, duplication is avoided. Optionally, one profile can be marked as "default", which will then be used for all repositories which doesn't explicitely reference a specific profile.
A profile can inherit settings from another profile, to even further encapsulate shared settings in a parent profile. This can for example be used to place global settings in a parent profile, such as clone depth and/or branch name, and remote specific settings in child profiles.

Thus, the priority order of any setting is:
1. The repository setting
2. The referenced profile setting (or default)
3. The parent profile (if any).
4. The grandparent profile (if any) etc. etc.

# Configuration
A specific configuration consists of layering one or many manifests on top of each other, where upper manifests override settings from lower manifests. The resulting manifest is stored as an "active manifest". Most grit commands are performed against this manifest.
Optionally, it can also refer to other locations where additional manifest files should be fetched (as a first step, before the configuration is initialized).

Layering of manifests can be useful in different use-cases:
* A base platform is developed by one team. This team maintains a manifest that includes all repositories of the base platform. Another team needs to customize the base platform for a specific customer. This includes adding new repositories and branching off some repositories (which needs to be customized). By placing all these manifest changes in its own customer manifest and overlaying it ontop of the base platform manifest, the second team doesn't need to branch off the base platform manifest. They can even place the customer manifest in its own git and by using the "fetch manifest" mechanism in the configuration file, fetch the base platform manifest automatically when the customer configuration file is initialized.`

# Data Extension
It is possible to add arbritarily json key/values as long as they start with "x-". grit will ignore all these keys. This can be used to store additional meta-data about the repositories, such as code license information, which is parsed by other tools.

# Generic commands
Generic commands are git commands that are transparently executed on all target repositories. For each repository, the result is printed as returned by git, prefixed with header lines that shows which repository the result is related to.
Essentially, grit here acts like an iterator of multiple repositories, executing the same git command.

Syntax:
```
grit <grit-options> <git-command> <git-command-parameters>
```

grit-options are:

| Option | Description |
| --- | --- |
| `-g <groups>` | Comma-separated list of groups (optional) |
| `-j <n>` | Perform the command using n parallel processes (default: 1) |
| `--verbose, -v` | Add some more verbose printing (to grit; not to the git command!) |

git-command is one of:
`remote, rebase, fetch, pull, push, merge, branch, status, stash, tag`

git-command-parameters are passed transparently to the specified git command.

Examples:

| Command | Description |
| --- | --- |
| `grit status` | Execute `git status` on all respositories in the active manifest. |
| `grit -j4 -g g1,g2 status -s` | Execute `git status -s` on all respositories belonging to either group `g1` or `g2`. Perform this operation using 4 parallel processes. |

# Clone command
Cloning repositories in the active manifest is not a generic command, but have grit specific logic. This is required since each repository has its own individual settings, as specified by the active manifest.

Syntax:
```
grit <grit-options> clone <clone-options>
```

grit-options are:

| Option | Description |
| --- | --- |
| `-g <groups>` | Comma-separated list of groups (optional) |
| `-j <n>` | Perform the command using n parallel processes (default: 1) |
| `--verbose, -v` | Add some more verbose printing (to grit; not to the git command!) |

clone-options are:

| Option | Description |
| --- | --- |
| `--mirror` | Clone with `--mirror` (see git documentation for more details) |
| `--bare` | Clone with `--bare` (see git documentation for more details) |
| `--reference <other_project_root>` | Clone with `--reference` to the same repository in another project (see git documentation for more details) |
| `--dissociate` | Clone with `--dissociate` (see git documentation for more details) |

Examples:

| Command | Description |
| --- | --- |
| `grit clone` | Clone all repositories in the active manifest.	|
| `grit -j4 -g g1,g2 clone` | Clone all respositories belonging to either group `g1` or `g2`. Perform this operation using 4 parallel processes. |
