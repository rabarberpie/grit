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
* Repositories: Contain the list of repositories that are included by the manifest. Optionally, may also include settings which take precedence over any profile settings (see below).

* Profiles: A profile contains all required settings to interact with the remote repository (using git). Typically, many repositories share the same settings; by placing these in a shared profile, duplication is avoided. Optionally, one profile can be marked as "default", which will be used for all repositories which don't explicitely reference a specific profile.
A profile can inherit settings from another profile, to even further encapsulate shared settings in a parent profile. This can for example be used to place global settings in a parent profile, such as clone depth and/or branch name, and remote specific settings in child profiles.

Thus, the priority order of any setting is:
1. The repository setting.
2. The referenced profile setting (or default).
3. The parent profile to above (if any).
4. The grandparent profile (if any) etc. etc.

All grit commands, except `grit init`, operate on a single manifest file called the active manifest, located in the GRIT_DIRECTORY directory (default: `.grit/_active_manifest.json`).

The `grit init` command is used to contruct the active manifest, either by copying a manifest file or by generating it from a configuration file. **Never modify the active manifest file manually!**

See [MANIFESTS](MANIFESTS.md) for detailed information about the manifest file syntax.

# Configurations
Configurations are optional to use and are usually only needed for large projects. It enables advanced manifest handling, see [CONFIGS](CONFIGS.md) for more information.

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
| `--force, -f` | Continue even if an error occurred. |
| `--no-log` | Do not log command details in the command log. By default, all executed commands by grit are appended in the `GRIT_DIRECTIRY/_command.log` log file. This log file can be inspected for details when error occurs etc. |
| `--verbose, -v` | Add some more verbose printing. |
| `--version` | Print grit version and then exit. |

# Init Command
The init command is used to initialize the active manifest, which is the basis for all other grit commands. This manifest file is located in the GRIT_DIRECTORY directory (default: `.grit`), where all other manifest and configuration files are located as well.

It is possible to call this command multiple times to re-initialize the active manifest, e.g. to switch manifest or to clone an additional manifest URL.

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
| `--depth <depth>` | Default clone depth if not specified in the active manifest (see git documentation for more details). |
| `--single-branch <yes/no>` | Default single-branch option if not specified in the active manifest. Note that `--single-branch yes` is mapped to git option `--single-branch` and `--single-branch no` is mapped to `--no-single-branch` (see git documentation for more details). |
| `--no-post-run` | If specified, the "run-after-clone" commands in the active manifest are skipped. |
| `--mirror` | Clone with `--mirror` (see git documentation for more details) |
| `--bare` | Clone with `--bare` (see git documentation for more details) |
| `--reference <other_project_root>` | Clone with `--reference` to the same repository in another project (see git documentation for more details) |
| `--dissociate` | Clone with `--dissociate` (see git documentation for more details) |

Examples:

| Command | Description |
| --- | --- |
| `grit clone` | Clone all repositories in the active manifest.	|
| `grit -j4 -g g1,g2 clone` | Clone all respositories belonging to either group `g1` or `g2`. Perform this operation using 4 parallel processes. |

Mirror example:

First, create a local mirror:
```
mkdir local_mirror
cd local_mirror
grit init https://github.com/rabarberpie/grit_test.git -b master -c grit_test/config
grit clone --mirror
cd ..
```

Next, create a new repo using the mirror as reference:
```
mkdir local_project
cd local_project
grit init https://github.com/rabarberpie/grit_test.git -b master -c grit_test/config
grit clone --reference ../local_mirror
```

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

git-command is any valid git command. Even locally defined git alias are possible. In practise, all non-special grit commands are treated as generic commands.

git-command-parameters are passed transparently to the specified git command.

Examples:

| Command | Description |
| --- | --- |
| `grit status` | Execute `git status` on all respositories in the active manifest. |
| `grit -j4 -g g1,g2 status -s` | Execute `git status -s` on all respositories belonging to either group `g1` or `g2` (or both). Perform this operation using 4 parallel processes. |

# Aliases
Long and frequent grit commads can be simplified by adding aliases to the (optional) `~/.gritaliases` file. Aliases work as simple text substitutions *before* the grit command line is parsed.

Example content of `~/.gritaliases`:
```
{
    "init_grit": "init https://github.com/rabarberpie/grit_test.git -b master",
    "init_grit2": "init https://github.com/rabarberpie/grit_test2.git"
}
```

Typing `grit init_grit -c config` is then equivalent to `grit init https://github.com/rabarberpie/grit_test.git -b master -c config`.
