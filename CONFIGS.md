# Configurations
Configuration files enable advanced manifest handling for large projects. This usage is optional; if one or more manifest files meet all your needs, you don´t have to make any configuration file.

The primary usage of configuration files is the ability to overlay manifests, where upper manifests override settings from lower manifests. Any manifest setting can be overriden. Each manifest file may only be a fraction, the only requirement is that the resulting manifest file is complete.

The resulting manifest is stored as the "active manifest", which is used by further grit commands.

Optionally, the configuration file can also refer to other locations where additional manifest files should be fetched (as a first step, before the configuration is initialized and manifest files are overlayed).

Layering of manifests can be useful in different use-cases:
* After cloning a project with many respositories, a developer wants to add a new repository or perhaps change branch on some existing repositories. These changes (only the differences) can be made in a "local manifest" which is then overlaid ontop of the project manifest. To simplify, the project master config file can include `local_manifest` as last manifest layer and then also include an empty `local_manifest.json` file. Everything is then setup for the developer to add the differences in this file.
* A base platform is developed by one team. This team maintains a manifest that includes all repositories of the base platform. Another team needs to customize the base platform for a specific customer. This includes adding new repositories and branching off some repositories (which needs to be customized). By placing all these manifest changes in its own customer manifest and overlaying it ontop of the base platform manifest, the second team doesn´t need to branch off the base platform manifest. They can even place the customer manifest in its own git and by using the "fetch manifest" mechanism in the configuration file, fetch the base platform manifest automatically when the customer configuration file is initialized.
* A product consists of a common base platform with a framework layer ontop. This framework comes in two variants: one basic and one with extensions. These two variants are maintained on different branches, "basic_master" and "extended_master".

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
