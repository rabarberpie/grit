#!/usr/bin/env python3
import os
import sys
import json
import argparse
import subprocess
import threading
import queue

LOG_FILE_NAME = "_commands.log"
ACTIVE_MANIFEST_FILE_NAME = "_active_manifest"  # .json is added automatically
GRIT_DIRECTORY = ".grit"
# Command queue extra size in addition to the number of parallel jobs. This is used to make sure the
# queue is always full (in practise).
COMMAND_QUEUE_EXTRA_SIZE = 2
JOB_QUEUE_TIMEOUT = 0.1   # 100ms


def json_manifest_object_hook(dct):
    if "profile" in dct:
        profile = Profile(dct["profile"])
        del dct["profile"]   # profile name is not a setting, remove it first.
        profile.set_settings(dct)
        return profile
    elif "repository" in dct:
        repo = Repository(dct["repository"])
        del dct["repository"]   # repository name is not a setting, remove it first.
        repo.set_settings(dct)
        return repo
    return dct


def json_manifest_encoder(obj):
    return obj.todict()


class JSONDecodeError(Exception):
    """ JSON Decode exception. """
    pass


class Settings(object):
    """ Base class for storing and managing settings in a generic way.
    Settings are stored in a key/value way in a regular dict.
    """

    def __init__(self, valid_keys: list):
        self.valid_keys = valid_keys
        self.settings = {}

    def set_settings(self, settings: dict):
        """ Extracts settings from a dict. Raises ValueError if invalid setting is present.
        NOTE: To remove a setting, set its value to null (in JSON file). This is mapped to None in Python.
        """
        # First, check if valid keys.
        for key in settings:
            if key in self.valid_keys:
                self.settings[key] = settings[key]
            elif key.startswith("x-"):
                # x- keys are for data extension. Just ignore silently.
                pass
            else:
                raise ValueError("Invalid settings key " + key + "!")

    def get_optional_setting(self, key: str, default=None):
        """ Get an optional setting. If setting key is missing, the default value is returned. """
        return self.settings.get(key, default)

    def get_mandatory_setting(self, key):
        """ Get a mandatory setting. If setting key is missing, the KeyError exception is raised. """
        try:
            return self.settings[key]
        except KeyError:
            raise KeyError("Settings key " + key + " is expected, but missing!")

    def get_settings(self):
        """ Get all settings, as a dict. NOTE: Do not modify returned dict! """
        return self.settings   # Just a reference is returned.

    def overlay(self, overlay_settings):
        """ Overlays the provided Settings object on top of existing one.
        This means that settings in the overlay Settings overwrite existing ones.
        To remove a setting, set its value to None (maps to "null" in JSON format).
        """
        self.settings.update(overlay_settings.get_settings())


class Profile(Settings):
    """ Stores all settings related to a profile. """
    valid_keys = ["remote-name", "remote-url", "remote-push-url",
                  "branch", "remote-branch", "single-branch"]

    def __init__(self, profile_name: str):
        super().__init__(Profile.valid_keys)
        self.profile_name = profile_name

    def get_profile_name(self):
        return self.profile_name

    def overlay(self, overlay_profile):
        """ Overlays the provided profile on top of existing one.
        This means that settings in the overlay profile overwrite existing ones.
        """
        # Call base class and override the settings.
        assert self.profile_name == overlay_profile.get_profile_name()
        super().overlay(overlay_profile)

    def todict(self):
        dct = {"profile": self.profile_name}
        dct.update(self.get_settings())
        return dct


class Repository(Settings):
    """ Stores all settings related to a repository. """
    # Valid keys include all Profile keys.
    valid_keys = ["use-profile", "directory", "groups"] + Profile.valid_keys

    def __init__(self, repo: str):
        super().__init__(Repository.valid_keys)
        self.repo = repo

    def get_repo(self):
        return self.repo

    def overlay(self, overlay_repo):
        """ Overlays the provided repository on top of existing one.
        This means that settings in the overlay repository overwrite existing ones.
        """
        # Call base class and override the settings.
        assert self.repo == overlay_repo.get_repo()
        super().overlay(overlay_repo)

    def todict(self):
        dct = {"repository": self.repo}
        dct.update(self.get_settings())
        return dct


class CommandExecutor(threading.Thread):
    """ Executes shell jobs in a separate thread.
    Each job consists of a sequence (list) of commands, which are executed in order (for dependency reasons).
    Each command contains all data related to it, such as the shell command line, but also the output
    printed on stdout and stderr. The result is processed by the caller, not by the executor.
    If an error occurs when executing a command, the job is aborted, i.e. no further commands inside the job
    are executed. However, this will not stop other jobs from being executed. This is up to the caller to handle.
    """

    class Command(object):
        """ Class to hold a command request and result data.
        No getters/setters or properties, fields are accessed directly.
        """

        def __init__(self, command_line: str, init_display_line: str=None, done_display_line: str=None, verbose=0,
                     result_handler=None, client_data=None):
            self.init_display_line = init_display_line  # Display line before starting command.
            self.done_display_line = done_display_line  # Display line after command completed.
            self.command_line = command_line   # The shell command line to execute.
            self.verbose = verbose   # The verbose level.
            self.result_code = -1    # The status code returned by the command. -1 means command not executed.
            self.result_output = None   # The combined output of stdout and stderr by the command (in string)
            self.result_handler = result_handler   # The result handler method to be called on the client side.
            self.client_data = client_data   # Arbitrary data set by the client.

        def execute(self):
            """ Execute the command and store the result. """
            if self.init_display_line is not None:
                print(self.init_display_line)
            # NOTE: universal_newlines makes output to be a string instead of bytes.
            result = subprocess.run(self.command_line, shell=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, universal_newlines=True)
            if result.returncode == 0:
                # Successfully executed command.
                if self.done_display_line is not None:
                    print(self.done_display_line)
            else:
                # If an error occurred, always print the details.
                output = "-" * 80 + "\n" + self.command_line + "\n"
                if result.stdout is not None:
                    output += result.stdout
                print(output, end="")    # Since multiple threads are printing, print all in single call.
            self.result_code = result.returncode
            self.result_output = result.stdout

    def __init__(self, request_queue: queue.Queue, result_queue: queue.Queue):
        super().__init__()
        self.request_queue = request_queue   # Each item is a list of Command instances (=a job).
        self.result_queue = result_queue     # Once processed, the command item is moved to the result queue.
        self.stop_signal = threading.Event()

    def signal_stop(self):
        """ Stop the thread. Note that this only sets a flag that is checked in the run loop, so it may take
        a while until it is really stopped.
        """
        self.stop_signal.set()

    def run(self):
        while not self.stop_signal.isSet():
            try:
                # Must have a timeout to enable checking stop request event even when queue is empty.
                job = self.request_queue.get(block=True, timeout=JOB_QUEUE_TIMEOUT)
                for command in job:
                    command.execute()
                    if command.result_code != 0:
                        # If an error occurred, no point to continue within the job (next commands likely depend on
                        # previous ones).
                        break
                # Moved the entire command jobs list to the result queue.
                self.result_queue.put(job, block=True)  # Never blocks since this queue is unlimited.
            except queue.Empty:
                # Queue get timeout, just check stop request event and try again.
                pass


class Manifest(object):
    """ Manages manifests. """

    def __init__(self):
        self.manifest = None
        self.dir_path = None
        self.request_queue = None
        self.result_queue = None
        self.pending_jobs = 0
        self.command_executors = []
        self.log_file_stream = None
        self.args = None

    def load(self, file_path: str):
        """ Load a manifest file (JSON format). """
        with open(file_path, "r") as file_stream:
            try:
                self.manifest = json.load(file_stream,
                                          object_hook=json_manifest_object_hook)
            except json.JSONDecodeError as err:
                raise JSONDecodeError(str(err) + " in file " + file_path)

        # Manifest files are relative to the config file directory.
        self.dir_path = os.path.dirname(file_path)

    def save(self, file_path: str):
        """ Save to a manifest file (JSON format). """
        with open(file_path, "w") as file_stream:
            json.dump(self.manifest, file_stream, indent=4, sort_keys=True, default=json_manifest_encoder)
            # Add a new line for a pretty ending.
            file_stream.write("\n")

    def validate_profiles(self):
        """ Do some sanity checking of the profiles. The final checking is done when performing an operation. """
        """ TODO: check that multiple profiles with same name doesn't exist!"""
        default_profile = self.manifest.get("default-profile", None)
        if default_profile is not None:
            try:
                profile = self.get_profile(default_profile)
            except ValueError:
                raise ValueError("The default profile " + default_profile + " is not defined!")
        global_profile = self.manifest.get("global-profile", None)
        if global_profile is not None:
            try:
                profile = self.get_profile(global_profile)
            except ValueError:
                raise ValueError("The global profile " + global_profile + " is not defined!")

    def validate_repos(self):
        """ Do some sanity checking of the repos. The final checking is done when performing an operation. """
        """ TODO: check that multiple repos with same name doesn't exist!"""
        try:
            if len(self.manifest["repositories"]) == 0:
                raise ValueError("No repositories are specified!")
            for repo in self.manifest["repositories"]:
                # get_profile raises ValueError if invalid profile is referenced.
                profile = self.get_profile(repo.get_optional_setting("use-profile"))
        except KeyError:
            raise ValueError("No repositories are specified!")

    def get_profiles(self):
        """ Get all profiles in a list. Each item is an instance of Profile.
        Return an empty list if not defined. """
        return self.manifest.get("profiles", list())

    def get_remove_profiles(self):
        """ Get all remove profiles in a list. Each item is a str (containing the profile name).
        Return an empty list if not defined. """
        return self.manifest.get("remove-profiles", list())

    def get_default_profile(self):
        """ Get the default profile, if defined. If not, None is returned.
        The default profile is used if a repo has no explicit use-profile setting.
        """
        for profile in self.get_profiles():
            if profile.get_profile_name() == self.manifest.get("default-profile", None):
                return profile
        else:
            return None

    def get_global_profile(self):
        """ Get the global profile, if defined. If not, None is returned.
        The global profile contain shared settings among all profiles. That is,
        if a setting is not found in a profile, the global profile is consulted.
        """
        for profile in self.get_profiles():
            if profile.get_profile_name() == self.manifest.get("global-profile", None):
                return profile
        else:
            return None

    def get_profile(self, profile_name: str):
        """ Get a profile, given its name. If profile name is None, the default profile is returned.
        Raises ValueError if a matching profile cannot be found.
        """
        if profile_name is None:
            profile_name = self.manifest.get("default-profile", None)
            if profile_name is None:
                raise ValueError("Default profile is implicitly referenced, but is undefined!")
        for profile in self.get_profiles():
            if profile.get_profile_name() == profile_name:
                return profile
        else:
            raise ValueError("Profile " + profile_name + " is referenced, but is undefined!")

    def add_profile(self, profile):
        """ Add a new profile. Raises ValueError if a profile with same name already exist. """
        profile_name = profile.get_profile_name()
        try:
            existing_profile = self.get_profile(profile_name)
        except ValueError:
            # Doesn't already exist. Add it.
            if "profiles" not in self.manifest:
                self.manifest["profiles"] = []
            self.manifest["profiles"].append(profile)
        else:
            raise ValueError("Profile " + profile_name + " already exist!")

    def remove_profile(self, profile_name: str):
        """ Remove a profile, given its name. If the name doesn't exist, this method is a no-op. """
        try:
            profile = self.get_profile(profile_name)
            index = self.get_profiles().index(profile)
            del self.get_profiles()[index]
        except ValueError:
            pass

    def get_repos(self):
        """ Get all repos in a list. Each item is in instance of Repository.
        Return an empty list if not defined. """
        return self.manifest.get("repositories", list())

    def get_remove_repos(self):
        """ Get all remove repositories in a list. Each item is a str (containing the repo name).
        Return an empty list if not defined. """
        return self.manifest.get("remove-repositories", list())

    def get_repo(self, repo_name: str):
        """ Get a repo, given its name.
        Raises ValueError if a matching repo cannot be found.
        """
        for repo in self.get_repos():
            if repo.get_repo() == repo_name:
                return repo
        else:
            raise ValueError("Repository " + repo_name + " is referenced, but is undefined!")

    def add_repo(self, repo):
        """ Add a new repository. Raises ValueError if a repository with same name already exist. """
        repo_name = repo.get_repo()
        try:
            existing_repo = self.get_repo(repo_name)
        except ValueError:
            # Doesn't already exist. Add it.
            if "repositories" not in self.manifest:
                self.manifest["repositories"] = []
            self.manifest["repositories"].append(repo)
        else:
            raise ValueError("Repository " + repo_name + " already exist!")

    def remove_repo(self, repo_name: str):
        """ Remove a repo, given its name. If the name doesn't exist, this method is a no-op. """
        try:
            repo = self.get_repo(repo_name)
            index = self.get_repos().index(repo)
            del self.get_repos()[index]
        except ValueError:
            pass

    def get_optional_setting(self, repo, key: str, default=None):
        """ Get an optional setting value based on priority order for a specific repo.
        The search order is: 1. repo, 2. referenced profile, 3. global profile.
        If a setting is not found, the default value is returned.
        """
        # Repo settings have highest priority.
        value = repo.get_optional_setting(key)
        if value is None:
            # Next comes the referenced profile settings.
            profile = self.get_profile(repo.get_optional_setting("use-profile"))
            value = profile.get_optional_setting(key)
            if value is None:
                # Last, check global profile - if defined.
                profile = self.get_global_profile()
                if profile is not None:
                    value = profile.get_optional_setting(key, default)
                else:
                    value = default
        return value

    def get_mandatory_setting(self, repo, key: str):
        """ Get a mandatory setting value based on priority order for a specific repo.
        The search order is: 1. repo, 2. referenced profile, 3. global profile.
        If a setting is not found, the KeyError exception is raised.
        """
        value = self.get_optional_setting(repo, key)
        if value is None:
            raise KeyError("Settings key " + key + " is expected, but missing!")
        else:
            return value

    def overlay(self, overlay_manifest):
        """ Overlays the provided manifest on top of existing one. """
        # First, remove all profiles and repos.
        for profile_name in overlay_manifest.get_remove_profiles():
            self.remove_profile(profile_name)
        for repo_name in overlay_manifest.get_remove_repos():
            self.remove_repo(repo_name)
        # Next, overlay default and global profile names.
        if "default-profile" in overlay_manifest.manifest:
            default_profile_name = overlay_manifest.manifest["default-profile"]
            self.manifest["default-profile"] = default_profile_name
        if "global-profile" in overlay_manifest.manifest:
            global_profile_name = overlay_manifest.manifest["global-profile"]
            self.manifest["global-profile"] = global_profile_name
        # Next, overlay the profiles.
        for profile in overlay_manifest.get_profiles():
            profile_name = profile.get_profile_name()
            try:
                existing_profile = self.get_profile(profile_name)
                existing_profile.overlay(profile)
            except ValueError:
                # Existing profile doesn't exist. Add as new profile.
                self.add_profile(profile)
        # Next, overlay the repos.
        for repo in overlay_manifest.get_repos():
            repo_name = repo.get_repo()
            try:
                existing_repo = self.get_repo(repo_name)
                existing_repo.overlay(repo)
            except ValueError:
                # Existing repo doesn't exist. Add as new repo.
                self.add_repo(repo)

    def set_args(self, args):
        """ Store the provided command arguments. Used by other methods. """
        self.args = args

    def prepare_for_commands(self):
        """ Prepare for executing commands. """
        # Open log file.
        if not args.no_log:
            self.log_file_stream = open(os.path.join(self.dir_path, LOG_FILE_NAME), "a+t")
        if self.args.parallel_jobs > 1:
            # Setup all command executors. Each item in request and result queue is a list of Command instances.
            self.request_queue = queue.Queue(args.parallel_jobs + COMMAND_QUEUE_EXTRA_SIZE)
            self.result_queue = queue.Queue()   # Result queue is unlimited.
            self.pending_jobs = 0
            for i in range(self.args.parallel_jobs):
                # Create new executor (thread).
                command_executor = CommandExecutor(self.request_queue, self.result_queue)
                command_executor.start()
                self.command_executors.append(command_executor)
        else:
            # If no parallel jobs, we don't spawn command executors. Instead, we run directly in the main thread.
            pass

    def cleanup_after_commands(self):
        # First, flush out remaining completed jobs.
        if self.args.parallel_jobs > 1:
            while self.pending_jobs > 0:
                job = self.result_queue.get(block=True)   # We can block now.
                self.pending_jobs -= 1
                self.handle_job_result(job)
            if self.log_file_stream is not None:
                self.log_file_stream.close()
        self.exit_commands(0)

    def exit_commands(self, result_code):
        """ Exit from executing commands. Ongoing commands will be completed, but no new ones
        will be started.
        """
        if self.args.parallel_jobs > 1:
            # First, signal stop to all command executors (threads).
            for command_executor in self.command_executors:
                command_executor.signal_stop()
            # Next, join them all.
            for command_executor in self.command_executors:
                command_executor.join()
        # Last, exit.
        exit(result_code)

    def queue_job(self, job):
        """ Queue up a new job and process any completed jobs. If request queue is full, this method
        block until space is made (=a command executor grab one).
        """
        if self.args.parallel_jobs > 1:
            # First, handle any completed job. If we catch an error here, we shouldn't queue a new job.
            while not self.result_queue.empty():
                job = self.result_queue.get(block=False)
                self.pending_jobs -= 1
                self.handle_job_result(job)
            self.request_queue.put(job, block=True)   # Will block if queue is full.
            self.pending_jobs += 1
        else:
            # Run the commands directly.
            for command in job:
                command.execute()
            self.handle_job_result(job)

    def handle_job_result(self, job):
        """ Handles the command result. This consists of logging the details in the log file.
        """
        for command in job:
            if command.result_handler is not None:
                # First, call dedicated result handler for additional processing.
                command.result_handler(command)
            if self.log_file_stream is not None:
                self.log_file_stream.write("-" * 80 + "\n")
                self.log_file_stream.write("- " + command.command_line + "\n")
                self.log_file_stream.write("-" * 80 + "\n")
                if command.result_output is not None:
                    self.log_file_stream.write(command.result_output)
            if command.result_code != 0 and not self.args.force_mode:
                # When not in force mode, exit at first error.
                # NOTE: There might be other successfully completed commands (or entire jobs) which are
                # still in the result queue and consequently will not be logged.
                # However, each error when running any command is always printed (by the command executor).
                self.exit_commands(command.result_code)

    def get_target_repos(self):
        """ Get all repos in a list, which is the target of the command. Each item is in instance of Repository.
        The target repos are controlled by the --group option. """
        if self.args.groups == "all":
            target_repos = self.get_repos()
        else:
            target_repos = []
            args_groups = self.args.groups.split(",")
            for repo in self.get_repos():
                repo_groups = repo.get_optional_setting("groups")  # This is a list of strings.
                if repo_groups is not None:
                    if isinstance(repo_groups, str):   # Allow a string instead of a list for a single group.
                        repo_groups = [repo_groups]    # Convert to a list.
                    for group in args_groups:
                        if group in repo_groups:
                            target_repos.append(repo)
                            break    # Must break to avoid adding same repo more than once.
        return target_repos

    def do_clone(self, args):
        """ Performs git clone on all repos. """
        self.set_args(args)
        self.prepare_for_commands()
        for repo in self.get_target_repos():
            job = []
            # Determine the local path first, since it is needed for additional commands in the git.
            directory = repo.get_optional_setting("directory")   # Can only be in repo.
            if directory is not None:
                local_path = directory
            else:
                local_path = repo.get_repo()
            cd_cmd_line = "cd " + local_path + " && "
            # First, clone the repository.
            cmd_line = "git clone"   # Add --progress to include progress info in the log file (note: one line each!)
            remote_name = self.get_optional_setting(repo, "remote-name", "origin")
            if remote_name != "origin":
                cmd_line += " --origin " + remote_name
            remote_branch = self.get_optional_setting(repo, "remote-branch")
            if remote_branch is None:
                # If a different remote branch is not specified, checkout branch directly in clone command.
                # Remote branch is also tracked.
                cmd_line += " --branch " + self.get_mandatory_setting(repo, "branch")
            single_branch = self.get_optional_setting(repo, "single-branch")
            if single_branch == "yes":
                cmd_line += " --single-branch"
            cmd_line += " " + self.get_mandatory_setting(repo, "remote-url") + "/" + repo.get_repo() + ".git"
            if directory is not None:
                cmd_line += " " + directory
            job.append(CommandExecutor.Command(cmd_line,
                                               "Started to clone " + repo.get_repo(),
                                               "Completed " + repo.get_repo()))
            # Next, configure the git, if needed.
            remote_push_url = self.get_optional_setting(repo, "remote-push-url")
            if remote_push_url is not None:
                # Add a different push URL.
                cmd_line = cd_cmd_line + "git remote set-url --add --push " + remote_name\
                           + " " + remote_push_url + "/" + repo.get_repo() + ".git"
                job.append(CommandExecutor.Command(cmd_line))
                # Finally, checkout the branch, if needed.
            if remote_branch is not None:
                # Must use capital -B to force create the branch; needed for example for master,
                # which is already created by clone above.
                cmd_line = cd_cmd_line + "git checkout -B " + self.get_mandatory_setting(repo, "branch")\
                           + " " + remote_name + "/" + remote_branch
                job.append(CommandExecutor.Command(cmd_line))
            self.queue_job(job)
        # All commands queued up. Gather all remaining results and then cleanup and exit.
        self.cleanup_after_commands()

    def handler_generic_command_result(self, command):
        """ Handler for generic command results. """
        print("-" * 80)
        print("- " + command.client_data)   # Contains repo name
        if self.args.verbose > 0:
            print("- Executed: " + command.command_line)
        print("-" * 80)
        if command.result_output is not None:
            print(command.result_output, end="")    # NL already included in result output.

    def do_generic(self, args):
        """ Performs a generic git command. Prints the output as is for each target repository. """
        self.set_args(args)
        self.prepare_for_commands()
        for repo in self.get_target_repos():
            job = []
            # Determine the local path first, since it is needed for additional commands in the git.
            directory = repo.get_optional_setting("directory")   # Can only be in repo.
            if directory is not None:
                local_path = directory
                client_data = repo.get_repo()
                if directory != repo.get_repo():
                    client_data += " in directory " + directory
            else:
                local_path = repo.get_repo()
                client_data = repo.get_repo()
            cd_cmd_line = "cd " + local_path + " && "
            # Rebase the repository.
            cmd_line = cd_cmd_line + "git " + args.command
            cmd_line += " " + " ".join(args.args)
            job.append(CommandExecutor.Command(cmd_line, None, None, args.verbose,
                                               self.handler_generic_command_result, client_data))
            self.queue_job(job)
        # All commands queued up. Gather all remaining results and then cleanup and exit.
        self.cleanup_after_commands()


def json_config_object_hook(dct):
    if "method" in dct:
        fetch_manifest = FetchManifest()
        fetch_manifest.set_settings(dct)
        return fetch_manifest
    return dct


class FetchManifest(Settings):
    """ Stores all settings related to a fetch of additional manifest(s). """
    valid_keys = ["method", "remote-url", "repository", "directory", "branch"]

    def __init__(self):
        super().__init__(FetchManifest.valid_keys)


class Config(object):
    """ Store all settings related to a specific configuration. """

    def __init__(self):
        self.config = None
        self.dir_path = None
        self.active_manifest = None

    def load(self, file_path: str):
        """ Loads a config file. """
        with open(file_path, "r") as file_stream:
            try:
                self.config = json.load(file_stream,
                                        object_hook=json_config_object_hook)
            except json.JSONDecodeError as err:
                raise JSONDecodeError(str(err) + " in file " + file_path)

        # Manifest files are relative to the config file directory.
        self.dir_path = os.path.dirname(file_path)

    def get_manifest_layers(self):
        """ Returns a list of all manifest layers. """
        return self.config["manifest-layers"]

    def get_fetch_manifests(self):
        """ Returns a list of all fetch manifests instructions. """
        return self.config["fetch-manifests"]

    def make_active_manifest(self):
        """ Overlays the specified manifests. """
        # First, create the final manifest.
        self.active_manifest = None
        for manifest_path in self.get_manifest_layers():
            manifest = Manifest()
            manifest.load(os.path.join(self.dir_path, manifest_path + ".json"))
            if self.active_manifest is None:
                self.active_manifest = manifest
            else:
                self.active_manifest.overlay(manifest)
        # Next, validate the final manifest. This is not a 100% check, just same sanity checks.
        # The final validation is done when actually executing a command, where all settings are fetched
        # as needed (mandatory or optional).
        if self.active_manifest is not None:
            self.active_manifest.validate_profiles()
            self.active_manifest.validate_repos()
            pass

    def get_active_manifest(self):
        """ Get the final manifest as determined by a previous call to make_active_manifest. """
        return self.active_manifest

    def save_active_manifest(self):
        """ Save the final manifest to the file system. """
        self.active_manifest.save(os.path.join(self.dir_path, ACTIVE_MANIFEST_FILE_NAME + ".json"))

    def load_active_manifest(self):
        """ Load the final manifest from the file system. """
        found_dir = False
        path = os.getcwd()
        while not found_dir:
            if os.path.exists(GRIT_DIRECTORY):
                found_dir = True
            else:
                # Go up one step
                parent_path = os.path.dirname(path)
                if parent_path != path:
                    path = parent_path
                else:
                    break
        if found_dir:
            self.active_manifest = Manifest()
            self.active_manifest.load(os.path.join(path, GRIT_DIRECTORY, ACTIVE_MANIFEST_FILE_NAME + ".json"))
            return self.active_manifest
        else:
            raise RuntimeError("Cannot find the " + GRIT_DIRECTORY + " directory!")


if __name__ == "__main__":
    # Generic git commands are those that are executed as in for each target repo. Any command args are
    # transparently added to the git command.
    generic_git_commands = ["remote", "rebase", "fetch", "pull", "push", "merge", "branch", "status"]
    parser = argparse.ArgumentParser(prog="grit",
                                     description="grit is a tool to manage many git repositories effeciently in a project.")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--force", "-f", action="store_true", dest="force_mode", help="continue even if an error occurred.")
    parser.add_argument("--jobs", "-j", type=int, default=1, dest="parallel_jobs", help="number of parallel jobs to perform. Default is 1.")
    parser.add_argument("--no-log", action="store_true", dest="no_log", help="do not add command details to log file.")
    parser.add_argument("--groups", "-g", action="store", dest="groups", default="all",
                        help="a repository must belong to at least one of the listed groups.\n"
                        "Multiple groups must be comma separated with no space between.")
    parser.add_argument("command", help="command to perform: init, clone, fetch, rebase, pull, upload")
    parser.add_argument("args", help="arguments to the command (depends on command)", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == "init":
        print("Initializing...", end="")
        config = Config()
        config.load(args.args[0])
        config.make_active_manifest()
        config.save_active_manifest()
        print(args)
        print("done.")
    elif args.command == "load":
        config = Config()
        config.load_active_manifest()
    elif args.command == "clone":
        config = Config()
        manifest = config.load_active_manifest()
        manifest.do_clone(args)
    # elif args.command == "status":
    #     config = Config()
    #     manifest = config.load_active_manifest()
    #     manifest.do_status(args)
    elif args.command in generic_git_commands:
        config = Config()
        manifest = config.load_active_manifest()
        manifest.do_generic(args)
    else:
        print("Unknown command: " + args.command)
