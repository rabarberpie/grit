# Manifests
Manifest files describe the repositories included in the project and all the settings/parameters required to interact with the remote server(s). They are formatted as JSON files, where each setting correspond to a key in the JSON tree.

# Repositories
The repositories section of the manifest file may contain below settings:

| Setting | Description |
| --- | --- |
| `repository` | The repository name on the remote server. |
| `directory` | The local directory path, relative the project root. If not specified, the local directory path is copied from the repository setting. NOTE: The directory separator must always be "/", regardless of the OS specific separator. grit will automatically convert "/" to the OS specific separator. |
| `groups` | The list of groups the repository belongs to. |
| `tag` | The tag or commit (SHA-1) to checkout when the repository is cloned. This override any branch setting in the profile(s). |
| `use-profile` | The name of the profile to use for additional (common) settings. If not specified, the profile referenced by the "default-profile" setting of the manifest is used. |
| Profile setting | Any profile setting can also be used in the repository to override the profile setting. |

# Profiles
The profiles section of the manifest file may contain below settings:

| Setting | Description |
| --- | --- |
| `inherit` | Specifies the name of parent profile (optional). |
| `remote-name` | The name of the remote server. If not specified, the git default value is used (`origin`). |
| `remote-url` | The URL of the remote server. The full URL to a repository is constructed via `remote-url/repository`. |
| `remote-push-url` | Only to be used if git pushes are to be made to a different URL than `remote-url`. |
| `branch` | The branch to create and checkout after a repository is cloned. The local branch is setup to track the remote branch. |
| `remote-branch` | Only to be used if the remote branch name is different from the local branch branch. |
| `single-branch` | If set to `yes`, then only the history leading to the tip of the specified branch is cloned. |

Example:

```
{
    "profiles": [
        {
            "profile": "global",
            "branch": "master"
        },
        {
            "profile": "default",
            "inherit": "global",
            "remote-name": "github",
            "remote-url": "https://github.com",
            "remote-push-url": "https://github-mirror.com"
        },
        {
            "profile": "android",
            "inherit": "global",
            "remote-name": "android",
            "remote-url": "https://android.googlesource.com",
            "single-branch": "yes"
        }
    ],

    "default-profile": "default",

    "repositories": [
        {
            "repository": "rabarberpie/grit",
            "directory": "local/grit",
            "groups": [ "g1", "g2", "g3" ],
	    "x-license": "Apache-2.0"
        },
        {
            "repository": "rabarberpie/grit_test",
            "groups": [ "g1", "g2", "g3" ],
	    "x-test": "yes"
        },
        {
            "repository": "rabarberpie/grit_test2",
            "groups": [ "g3" ],
            "single-branch": "yes",
	    "x-test": "yes"
        },
        {
            "repository": "platform/build",
            "groups": [ "g3", "g4" ],
            "use-profile": "android"
        }
    ]
}
```
