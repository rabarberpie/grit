# Configurations
Configuration files enable advanced manifest handling for large projects. This usage is optional; if one or more manifest files meet all your needs, you don´t have to make any configuration file.

The primary usage of configuration files is the ability to overlay manifests, where upper manifests override settings from lower manifests. Any manifest setting can be overriden. *Each manifest file may be a fraction only, the only requirement is that the resulting manifest file is complete.*

The resulting manifest is stored as the active manifest, which is used by further grit commands.

Optionally, the configuration file can also refer to other locations where additional manifest files should be fetched (as a first step, before the configuration is initialized and manifest files are overlayed).

Layering of manifests can be useful in different use-cases:
* After cloning a project with many respositories, a developer wants to add a new repository or perhaps change branch on some existing repositories. These changes (only the differences) can be made in a "local manifest" which is then overlaid ontop of the project manifest. To simplify, the project master config file can include `local_manifest` as last manifest layer and then also include an empty `local_manifest.json` file. Everything is then setup for the developer to add the differences in this file.

Example, where a local manifest sets/overrides the clone depth of the global profile (assuming all profiles inherit from this one, the clone depth will be valid for all repositories):

`config.json`:
```
{
    "manifest-layers": [
	"main_manifest",
	"local_manifest"
    ]
}
```
`local_manifest.json`:
```
{
    "profiles": [
        {
            "profile": "global",
            "depth": "4"
        }
    ]
}
```
* A base platform is developed by one team. This team maintains a manifest that includes all repositories of the base platform. Another team needs to customize the base platform for a specific customer. This includes adding new repositories and branching off some repositories (which needs to be customized). By placing all these manifest changes in its own customer manifest and overlaying it ontop of the base platform manifest, the second team doesn´t need to branch off the base platform manifest. They can even place the customer manifest in its own git and by using the "fetch manifest" mechanism in the configuration file, fetch the base platform manifest automatically when the customer configuration file is initialized.

Example, where below config file is located in a customer specific manifest git and grit initialized with `-d cust_manifests`:

`cust_manifests/config.json`:
```
{
    "fetch-manifests": [
	{
	    "method": "git",
	    "remote-url": "https://myserver.com",
	    "repository": "manifests",
	    "branch": "master",
	    "directory": "base_manifests"
	}
    ],

    "manifest-layers": [
	"/base_manifests/main",
	"main"
    ]
}
```
The customer specific manifest overrides the branch name of `comp1` (of the base platform), adds the customer specific `comp2`, and removes `comp3` and `comp4`:

`cust_manifests/main.json`:
```
{
    "repositories": [
        {
            "repository": "base_platform/comp1",
	    "branch": "customer_branch"
        },
        {
            "repository": "cust_platform/comp2",
	    "branch": "customer_branch"
        }
    ],

    "remove-repositories": [
        "base_platform/comp3",
        "base_platform/comp4"
    ]
}
```
* A product consists of a common base platform with a framework layer ontop. This framework comes in two variants: one basic and one with extensions. These two variants are maintained on different branches, "basic_master" and "extended_master".

Example, where the base platform is managed by its own manifest file, the framework repositories are listed (without branch information) in a common framework manifest, and where the framework branch information is provided by separate basic and extended framework overlay manifests:

`basic_config.json`:
```
{
    "manifest-layers": [
	"base_platform",
	"framework",
	"basic_framework"
    ]
}
```
`extended_config.json`:
```
{
    "manifest-layers": [
	"base_platform",
	"framework",
	"extended_framework"
    ]
}
```
`framework.json`:
```
{
    "profiles": [
        {
            "profile": "default",
            "remote-name": "origin",
            "remote-url": "https://myserver.com",
        }
    ],

    "default-profile": "default",
    
    "repositories": [
        {
            "repository": "framework/comp1"
        },
        {
            "repository": "framework/comp2"
        }
    ]
}
```
`basic_framework.json`:
```
{
    "profiles": [
        {
            "profile": "default",
	    "branch": "basic_master"
        }
    ]
}
```
`extended_framework.json`:
```
{
    "profiles": [
        {
            "profile": "default",
	    "branch": "extended_master"
        }
    ]
}
```

Note that all above files are located in the same manifest git and branch.

# Examples

```
{
    "fetch-manifests": [
	{
	    "method": "git",
	    "remote-url": "https://github.com",
	    "repository": "rabarberpie/grit_test2",
	    "branch": "master",
	    "directory": "manifests2"
	}
    ],
	
    "manifest-layers": [
	"manifest1",
	"manifest2",
	"/manifests2/manifest1"
    ]
}
```
