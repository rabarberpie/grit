# grit
grit is a tool for managing many git repositories in a single project; it is an alternative to repo.

It is designed with below principles:
* Stay close to the git concepts and terminologies, including option names.
* Layered settings, making it easy to override a specific setting by overlaying.
* Use JSON as format for settings files, for easy parsing, as well as easy manual editing.

# Quick Overview
A simple manifest, consisting of 3 different repositories, all located on github:
```
{
    "profiles": [
	{
	    "profile": "github",
	    "remote-name": "github",
	    "remote-url": "https://github.com"
	}
    ],

    "repositories": [
	{
	    "repository": "rabarberpie/grit",
	    "directory": "mylocal/grit",
	    "groups": ["g1"],
	    "use-profile": "github"
	},
	{
	    "repository": "rabarberpie/grit_test",
	    "groups": ["g1", "g2"],
	    "use-profile": "github"
	},
	{
	    "repository": "rabarberpie/grit_test2",
	    "groups": ["g3"],
	    "use-profile": "github"
	}
    ]
}
```
A profile describes the common settings/data needed to interact with the remote repository. The actual repositories and where to store them locally are listed separately.

Once the manifest has been initialized, the repositories are cloned via:
```
grit clone
```

After that, you can use the normal git commands, but performed on all repositories (or limited to the ones belonging to certain groups).
For example,
```
grit checkout -b mybranch
```
results in:
```
--------------------------------------------------------------------------------
- mylocal/grit
--------------------------------------------------------------------------------
Switched to a new branch 'mybranch'
--------------------------------------------------------------------------------
- rabarberpie/grit_test
--------------------------------------------------------------------------------
Switched to a new branch 'mybranch'
--------------------------------------------------------------------------------
- rabarberpie/grit_test2
--------------------------------------------------------------------------------
Switched to a new branch 'mybranch'
```

One of the key strengths of grit is the ability to overlay manifest files, which is very handy in large systems. Read on to find out more...

# Installation
Copy grit.py to ~/bin and make it executable:

```
git clone https://github.com/rabarberpie/grit.git
mkdir ~/bin
cp grit/grit.py ~/bin/grit
chmod +x ~/bin/grit
```

# Manifests
Manifest files are the core settings files and have below sections:
* Repositories: Contain the list of repositories that are included by the manifest. Optionally, may also include parameters/options which override the profile settings (see below).

* Profiles: A profile contains all required settings/parameters/options to interact with the remote repository (using git). Typically, many repositories share the same settings; by placing these in a shared profile, duplication is avoided. Optionally, one profile can be marked as "default", which will be used for all repositories which don't explicitely reference a specific profile.
A profile can inherit settings from another profile, to even further encapsulate shared settings in a parent profile. This can for example be used to place global settings in a parent profile, such as clone depth and/or branch name, and remote specific settings in child profiles.

Thus, the priority order of any setting is:
1. The repository setting
2. The referenced profile setting (or default)
3. The parent profile to above (if any).
4. The grandparent profile (if any) etc. etc.

# Configuration
A specific configuration consists of layering one or many manifests on top of each other, where upper manifests override settings from lower manifests. The resulting manifest is stored as an "active manifest". Most grit commands are performed against this manifest.
Optionally, it can also refer to other locations where additional manifest files should be fetched (as a first step, before the configuration is initialized).

Layering of manifests can be useful in different use-cases:
* After cloning a project with many respositories, a developer wants to add a new repository or perhaps change branch on some existing repositories. These changes (only the differences) can be made in a "local manifest" which is then overlaid ontop of the project manifest. To simplify, the project master config file can include `local_manifest` as last manifest layer and then also include an empty `local_manifest.json` file. Everything is then setup for the developer to add the differences in this file.
* A base platform is developed by one team. This team maintains a manifest that includes all repositories of the base platform. Another team needs to customize the base platform for a specific customer. This includes adding new repositories and branching off some repositories (which needs to be customized). By placing all these manifest changes in its own customer manifest and overlaying it ontop of the base platform manifest, the second team doesn't need to branch off the base platform manifest. They can even place the customer manifest in its own git and by using the "fetch manifest" mechanism in the configuration file, fetch the base platform manifest automatically when the customer configuration file is initialized.
* A product consists of a common base platform with a framework layer ontop. This framework comes in two variants: one basic and one with extensions. These two variants are maintained on different branches, "basic_master" and "extended_master".

# Data Extension
It is possible to add arbritarily json key/values as long as they start with "x-". grit will ignore all these keys. This can be used to store additional meta-data about the repositories, such as code license information, which is parsed by other tools.

# Grit Options
There is a set of options to grit that are common to all commands. These always follow immediately after the grit command.

Syntax:
```
grit <grit-options> <command> <command-parameters/options>
```

grit-options are:

| Option | Description |
| --- | --- |
| `--groups, -g <groups>` | Comma-separated list of groups (optional). The command is only performed for repositories belonging to at least one of listed groups. |
| `--jobs, -j <n>` | Perform the command using n parallel processes (default: 1). Particularly useful to speed up clone operations. |
| `--force, -f` | Continue even if an error occurred |
| `--verbose, -v` | Add some more verbose printing |

# Init Command
The init command is used to initialize the active manifest, which is the basis for all other grit commands. It is possible to call this command multiple times to re-initialize the active manifest, e.g. to switch manifest or to clone an additional manifest URL.

Syntax:
```
grit <grit-options> init <manifest-url> <init-options>
```

If `manifest-url` is specified, this URL is cloned into the GRIT_DIRECTORY as a first step.

init-options are:

| Option | Description |
| --- | --- |
| `--directory, -d` | The local directory path, relative to GRIT_DIRECTORY, where to clone the specified manifest URL. If not specified, the local directory path is taken from the last part of the URL (as git does). |
| `--branch, -b` | The branch to checkout after the manifest URL has been cloned. |
| `--manifest, -m` | The manifest to use as active manifest. The path is relative to GRIT_DIRECTORY. NOTE: The directory separator must always be "/", regardless of the OS specific separator. grit will automatically convert "/" to the OS specific separator. This option is mutually exclusive with the config option.  |
| `--config, -c` | The configuration to use to generate an active manifest. The path is relative to GRIT_DIRECTORY. NOTE: The directory separator must always be "/", regardless of the OS specific separator. grit will automatically convert "/" to the OS specific separator. This option is mutually exclusive with the manifest option. |

Examples:

| Command | Description |
| --- | --- |
| `grit init https://github.com/rabarberpie/grit_test.git -b master` | Clone the manifest URL into `GRIT_DIRECTORY/grit_test` (but no active manifest is generated). |
| `grit init -m grit_test/manifest1` | Use manifest1 as active manifest. |

Note that above examples can be combined into `grit init https://github.com/rabarberpie/grit_test.git -b master -m grit_test/manifest1`

# Clone Command
The clone command is used to clone the repositories as specified by the active manifest. This is typically called after the init command.

Syntax:
```
grit <grit-options> clone <clone-options>
```

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

# For-each command
The for-each command executes a specified bash command on each target repository.

Syntax:
```
grit <grit-options> foreach <bash-command-line>
```

bash-command-line should be a single quoted argument. If not quoted, all arguments will be passed on, but environment variables may be not available as expected.

Below environment variables are available to the bash command:

| Variable | Description |
| --- | --- |
| `LOCAL_PATH` | The local directory path where the repository is stored. |
| `REMOTE_REPO` | The remote repository path. |
| `REMOTE_NAME` | The remote name. |
| `REMOTE_URL` | The remote URL. |

Examples:

| Command | Description |
| --- | --- |
| `grit foreach pwd` | Print the current working directory. |
| `grit foreach 'echo $LOCAL_PATH; echo $REMOTE_REPO'` | Print the local path and remote repository path. |

# Snapshot Command
The shapshot command creates a new snapshot manifest, which is a copy of the current active manifest, expect that for each target repo, the current HEAD reference (SHA-1) is inserted as "tag" in the manifest. Since "tag" overrides any branch definition in profiles, the snapshot manifest can be used to store the current state. However, keep in mind that if git performs a cleanup, the specified HEAD reference may no longer be available.
A safer way to make a snapshot is to make a tag on each repo instead (`grit tag <tag_name>`).

Syntax:
```
grit <grit-options> snapshot <snapshot-manifest-name>
```

The snapshot-manifest-name (without .json) is optional. If not specified, a unique name is created based on date and time: "snapshot_YYYYMMDD_HHMMSS".
The snapshot manifest file is stored in the GRIT_DIRECTORY and can be used in `grit init -m <snapshot-manifest-name>` to restore the snapshot state.

# Generic Commands
Generic commands are git commands that are transparently executed on all target repositories. For each repository, the result is printed as returned by git, prefixed with header lines that shows which repository the result is related to.
Essentially, grit here acts like an iterator over multiple repositories, executing the same git command.

Syntax:
```
grit <grit-options> <git-command> <git-command-parameters>
```

git-command is any valid git command. Even locally defined git alias are possible. Essentially, all non-special grit commands are treated as generic commands.

git-command-parameters are passed transparently to the specified git command.

Examples:

| Command | Description |
| --- | --- |
| `grit status` | Execute `git status` on all respositories in the active manifest. |
| `grit -j4 -g g1,g2 status -s` | Execute `git status -s` on all respositories belonging to either group `g1` or `g2` (or both). Perform this operation using 4 parallel processes. |
