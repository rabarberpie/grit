#!/usr/bin/env python3
import os
import sys
import time
import json
import argparse
import subprocess
import threading
import queue
import logging

logger = logging.getLogger(__name__)

GRIT_DIRECTORY = ".grit"
LOG_FILE_NAME = "_commands.log"
ACTIVE_MANIFEST_FILE = "_active_manifest"   # .json is added automatically
GRIT_ALIASES_FILE = ".gritaliases"
ACTIVE_CONFIG_FILE = "_config"   # Contains the current active config (file path to config file except .json)
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

    def get_settings(self):
        """ Get all settings, as a dict. NOTE: Do not modify returned dict! """
        return self.settings   # Just a reference is returned.

    def set_settings(self, settings: dict):
        """ Extracts/updates settings from a dict. Raises ValueError if invalid setting is present.
        NOTE: To remove a setting, set its value to null (in JSON file). This is mapped to None in Python.
        """
        # First, check if valid keys.
        for key in settings:
            if key in self.valid_keys:
                self.settings[key] = settings[key]
            elif key.startswith("x-"):
                # x- keys are for data extension. Just ignore silently.
                logger.debug("Found extension key " + key + ", ignoring silently.")
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

    def set_setting(self, key: str, value):
        self.settings[key] = value

    def remove_setting(self, key):
        if key in self.settings:
            del self.settings[key]

    def overlay(self, overlay_settings):
        """ Overlays the provided Settings object on top of existing one.
        This means that settings in the overlay Settings overwrite existing ones.
        To remove a setting, set its value to None (maps to "null" in JSON format).
        """
        self.settings.update(overlay_settings.get_settings())


class Profile(Settings):
    """ Stores all settings related to a profile. """
    valid_keys = ["inherit", "remote-name", "remote-url", "remote-push-url",
                  "branch", "remote-branch", "single-branch", "depth"]

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
        logger.debug("Overlaying profile " + self.profile_name)
        assert self.profile_name == overlay_profile.get_profile_name()
        super().overlay(overlay_profile)

    def todict(self):
        dct = {"profile": self.profile_name}
        dct.update(self.get_settings())
        return dct


class Repository(Settings):
    """ Stores all settings related to a repository. """
    # Valid keys include all Profile keys.
    valid_keys = ["use-profile", "directory", "groups", "tag"] + Profile.valid_keys

    def __init__(self, repo: str):
        super().__init__(Repository.valid_keys)
        self.repo = repo

    def get_repo(self):
        return self.repo

    def get_local_path(self):
        """ Returns the local path (relative to project root directory). """
        # Note that "directory" can only be in repo, not in any profile. Default to repo name.
        directory = self.get_optional_setting("directory", self.get_repo())
        # Convert logical path (always with "/") to OS specific path.
        directory_parts = directory.split("/")
        return os.path.join(*directory_parts)

    def overlay(self, overlay_repo):
        """ Overlays the provided repository on top of existing one.
        This means that settings in the overlay repository overwrite existing ones.
        """
        # Call base class and override the settings.
        logger.debug("Overlaying repository " + self.repo)
        assert self.repo == overlay_repo.get_repo()
        super().overlay(overlay_repo)

    def todict(self):
        dct = {"repository": self.repo}
        dct.update(self.get_settings())
        return dct


class Command(object):
    """ Class to hold a command request and result data.
    No getters/setters or properties, fields are accessed directly.
    """

    def __init__(self, command_line: str, init_display_line: str=None, done_display_line: str=None,
                 print_errors=True, verbose=0, result_handler=None, client_data=None):
        self.init_display_line = init_display_line  # Display line before starting command.
        self.done_display_line = done_display_line  # Display line after command completed.
        self.command_line = command_line   # The shell command line to execute.
        self.print_errors = print_errors   # Print output if command exited with error.
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
        logger.debug("Started to run " + self.command_line)
        result = subprocess.run(self.command_line, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, universal_newlines=True)
        if result.returncode == 0:
            # Successfully executed command.
            logger.debug("Successful execution of " + self.command_line)
            if self.done_display_line is not None:
                print(self.done_display_line)
        else:
            # If an error occurred, always print the details.
            logger.debug("Failed to execute " + self.command_line)
            if self.print_errors:
                output = "-" * 80 + "\n" + self.command_line + "\n"
                if result.stdout is not None:
                    output += result.stdout
                print(output, end="")    # Since multiple threads are printing, print all in single call.
        self.result_code = result.returncode
        self.result_output = result.stdout


class CommandExecutor(threading.Thread):
    """ Executes shell jobs in a separate thread.
    Each job consists of a sequence (list) of commands, which are executed in order (for dependency reasons).
    Each command contains all data related to it, such as the shell command line, but also the output
    printed on stdout and stderr. The result is processed by the caller, not by the executor.
    If an error occurs when executing a command, the job is aborted, i.e. no further commands inside the job
    are executed. However, this will not stop other jobs from being executed. This is up to the caller to handle.
    """

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
        self.manifest_path = None
        self.request_queue = None
        self.result_queue = None
        self.pending_jobs = 0
        self.command_executors = []
        self.log_file_stream = None
        self.args = None

    def load(self, manifest_path: str):
        """ Load a new manifest file (JSON format). The manifest_path argument is the path within GRIT_DIRECTORY,
        except that the .json file extension is to be omitted.
        Note that manifest_path must use "/" as directory separator, regardless of native OS separator.
        """
        self.manifest_path = manifest_path
        path_parts = (manifest_path + ".json").split("/")
        file_path = os.path.join(self.get_root_path(), GRIT_DIRECTORY, *path_parts)
        logger.debug("Loading manifest file " + file_path)
        with open(file_path, "r") as file_stream:
            try:
                self.manifest = json.load(file_stream,
                                          object_hook=json_manifest_object_hook)
            except json.JSONDecodeError as err:
                raise JSONDecodeError(str(err) + " in file " + file_path)

    def save(self, manifest_path: str):
        """ Save to a manifest file (JSON format). The manifest_path argument is the path within GRIT_DIRECTORY,
        except that the .json file extension is to be omitted.
        Note that manifest_path must use "/" as directory separator, regardless of native OS separator.
        """
        path_parts = (manifest_path + ".json").split("/")
        file_path = os.path.join(self.get_root_path(), GRIT_DIRECTORY, *path_parts)
        logger.debug("Saving manifest file " + file_path)
        with open(file_path, "w") as file_stream:
            json.dump(self.manifest, file_stream, indent=4, sort_keys=True, default=json_manifest_encoder)
            # Add a new line for a pretty ending.
            file_stream.write("\n")

    @staticmethod
    def get_root_path():
        """ Get the full path to the project root directory.
        Assumes that the current working directory is at, or below, project root.
        """
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
            logger.debug("Project root path is " + path)
            return path
        else:
            raise RuntimeError("Cannot find the " + GRIT_DIRECTORY + " directory!")

    def load_active_manifest(self):
        """ Load the active manifest from the file system. Automatically finds the active
        manifest file, even if current working directory is below project root. """
        self.load(ACTIVE_MANIFEST_FILE)

    def save_active_manifest(self):
        """ Save the manifest as new active manifest to the file system. """
        self.save(ACTIVE_MANIFEST_FILE)

    def validate_profiles(self):
        """ Do some sanity checking of the profiles. The final checking is done when performing an operation. """
        """ TODO: check that multiple profiles with same name doesn't exist!"""
        logger.debug("Validating profiles.")
        default_profile = self.manifest.get("default-profile", None)
        if default_profile is not None:
            try:
                profile = self.get_profile(default_profile)
            except ValueError:
                raise ValueError("The default profile " + default_profile + " is not defined!")

    def validate_repos(self):
        """ Do some sanity checking of the repos. The final checking is done when performing an operation. """
        """ TODO: check that multiple repos with same name doesn't exist!"""
        logger.debug("Validating profiles.")
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

    def get_run_after_clone_commands(self):
        """ Get all run after clone commands. Each item is a str (containing the bash command line).
        Return an empty list if not defined. """
        return self.manifest.get("run-after-clone", list())

    def get_default_profile(self):
        """ Get the default profile, if defined. If not, None is returned.
        The default profile is used if a repo has no explicit use-profile setting.
        """
        for profile in self.get_profiles():
            if profile.get_profile_name() == self.manifest.get("default-profile", None):
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
        logger.debug("Adding profile " + profile_name)
        try:
            existing_profile = self.get_profile(profile_name)
        except ValueError:
            # Doesn't already exist. Add it.
            if "profiles" not in self.manifest:
                # First profile in manifest, create empty list first.
                self.manifest["profiles"] = []
            self.manifest["profiles"].append(profile)
        else:
            raise ValueError("Profile " + profile_name + " already exist!")

    def remove_profile(self, profile_name: str):
        """ Remove a profile, given its name. If the name doesn't exist, this method is a no-op. """
        logger.debug("Removing profile " + profile_name)
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
        logger.debug("Adding repository " + repo_name)
        try:
            existing_repo = self.get_repo(repo_name)
        except ValueError:
            # Doesn't already exist. Add it.
            if "repositories" not in self.manifest:
                # First repository in manifest, create empty list first.
                self.manifest["repositories"] = []
            self.manifest["repositories"].append(repo)
        else:
            raise ValueError("Repository " + repo_name + " already exist!")

    def remove_repo(self, repo_name: str):
        """ Remove a repo, given its name. If the name doesn't exist, this method is a no-op. """
        logger.debug("Removing repository " + repo_name)
        try:
            repo = self.get_repo(repo_name)
            index = self.get_repos().index(repo)
            del self.get_repos()[index]
        except ValueError:
            pass

    def get_optional_setting(self, repo, key: str, default=None):
        """ Get an optional setting value based on priority order for a specific repo.
        The search order is: 1. repo, 2. referenced profile, 3. parent profile, 4. grandparent profile etc.
        If a setting is not found, the default value is returned.
        """
        # Repo settings have highest priority.
        value = repo.get_optional_setting(key)
        if value is None:
            # Next comes the referenced profile settings.
            profile = self.get_profile(repo.get_optional_setting("use-profile"))
            value = profile.get_optional_setting(key)
            if value is None:
                # Check parent profile settings (and then grandparent etc.)
                profile_name = profile.get_optional_setting("inherit")
                while profile_name is not None:
                    profile = self.get_profile(profile_name)
                    value = profile.get_optional_setting(key)
                    if value is not None:
                        break
                    else:
                        profile_name = profile.get_optional_setting("inherit")
                else:
                    value = default
        return value

    def get_mandatory_setting(self, repo, key: str):
        """ Get a mandatory setting value based on priority order for a specific repo.
        The search order is: 1. repo, 2. referenced profile, 3. parent profile, 4. grandparent profile etc.
        If a setting is not found, the KeyError exception is raised.
        """
        value = self.get_optional_setting(repo, key)
        if value is None:
            raise KeyError("Settings key " + key + " is expected, but missing!")
        else:
            return value

    def overlay(self, overlay_manifest):
        """ Overlays the provided manifest on top of existing one. """
        logger.debug("Overlaying manifest.")
        # First, remove all profiles and repos.
        for profile_name in overlay_manifest.get_remove_profiles():
            self.remove_profile(profile_name)
        for repo_name in overlay_manifest.get_remove_repos():
            self.remove_repo(repo_name)
        # Next, overlay default profile name.
        if "default-profile" in overlay_manifest.manifest:
            default_profile_name = overlay_manifest.manifest["default-profile"]
            self.manifest["default-profile"] = default_profile_name
            logger.debug("Overlaying default profile to " + default_profile_name)
        # Next, overlay any run after clone commands. NOTE: overlaying means extending!
        if "run-after-clone" in overlay_manifest.manifest:
            run_after_clone_commands = overlay_manifest.manifest["run-after-clone"]   # This is a list.
            if "run-after-clone" in self.manifest:
                logger.debug("Extending run after clone with " + ",".join(run_after_clone_commands))
                self.manifest["run-after-clone"].extend(run_after_clone_commands)
            else:
                logger.debug("Creating run after clone with " + ",".join(run_after_clone_commands))
                self.manifest["run-after-clone"] = run_after_clone_commands
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
        if not self.args.no_log:
            self.log_file_stream = open(os.path.join(self.get_root_path(), GRIT_DIRECTORY, LOG_FILE_NAME), "a+t")
            self.log_file_stream.write("*" * 80 + "\n")
            self.log_file_stream.write("* " + time.strftime("%Y%m%d %H:%M:%S") + "\n")
            self.log_file_stream.write("*" * 80 + "\n")
        if self.args.parallel_jobs > 1:
            # Setup all command executors. Each item in request and result queue is a list of Command instances.
            self.request_queue = queue.Queue(self.args.parallel_jobs + COMMAND_QUEUE_EXTRA_SIZE)
            self.result_queue = queue.Queue()   # Result queue is unlimited.
            self.pending_jobs = 0
            for i in range(self.args.parallel_jobs):
                # Create new executor (thread).
                logger.debug("Creating new command executor.")
                command_executor = CommandExecutor(self.request_queue, self.result_queue)
                command_executor.start()
                self.command_executors.append(command_executor)
        else:
            # If no parallel jobs, we don't spawn command executors. Instead, we run directly in the main thread.
            logger.debug("No parallel jobs; will run all jobs in same process.")
            pass

    def finish_commands(self):
        # First, finish remaining completed jobs. Will block until everything is done or error occurs.
        logger.debug("Finishing command execution.")
        if self.args.parallel_jobs > 1:
            while self.pending_jobs > 0:
                job = self.result_queue.get(block=True)   # We can block now.
                self.pending_jobs -= 1
                self.handle_job_result(job)   # If error, exit is called (unless force mode).
            if self.log_file_stream is not None:
                logger.debug("Closing log file.")
                self.log_file_stream.close()
        # Last, exit command execution.
        self.exit_commands()

    def exit_commands(self):
        """ Exit from executing commands. Ongoing commands will be completed, but no new ones
        will be started.
        """
        logger.debug("Exiting command execution.")
        if self.args.parallel_jobs > 1:
            # First, signal stop to all command executors (threads).
            for command_executor in self.command_executors:
                command_executor.signal_stop()
            # Next, join them all.
            for command_executor in self.command_executors:
                command_executor.join()

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
                if command.result_code != 0:
                    # If an error occurred, no point to continue within the job (next commands likely depend on
                    # previous ones).
                    break
            self.handle_job_result(job)

    def handle_job_result(self, job):
        """ Handles the command result. This consists of logging the details in the log file.
        """
        logger.debug("Handle job result.")
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
                self.exit_commands()
                exit(command.result_code)

    def get_target_repos(self, groups=None):
        """ Get all repos in a list, which is the target of the command. Each item is an instance of Repository.
        groups is a string of comma-separated list of groups (as specified by the --group option.)
        """
        if groups is None:
            target_repos = self.get_repos()
        else:
            target_repos = []
            args_groups = groups.split(",")
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
        clone_parser = argparse.ArgumentParser()
        # Mirror options can only be specified as clone command options (not in manifest).
        clone_parser.add_argument("--reference", action="store", dest="reference", default=None)
        clone_parser.add_argument("--dissociate", action="store_true", dest="dissociate")
        clone_parser.add_argument("--bare", action="store_true", dest="bare")
        clone_parser.add_argument("--mirror", action="store_true", dest="mirror")
        # Some default settings if not specified in the manifest.
        clone_parser.add_argument("--single-branch", action="store", dest="single_branch", default=None)
        clone_parser.add_argument("--depth", action="store", dest="depth", type=int, default=None)
        # No post run is used to disable executing the "run-after-clone" commands in the manifest.
        clone_parser.add_argument("--no-post-run", action="store_true", dest="no_post_run")
        # Parse the clone args.
        clone_args = clone_parser.parse_args(args.args)   # Parse args after clone.
        self.set_args(args)
        self.prepare_for_commands()
        for repo in self.get_target_repos(args.groups):
            job = []
            # Determine the local path first, since it is needed for additional commands in the git.
            local_path = repo.get_local_path()
            if os.path.exists(local_path):
                # Local repo already exist, skip this one silently. For instance, if you re-clone, avoid
                # lots of errors for all existing repos.
                if args.verbose > 0:
                    print("Skipping " + repo.get_repo() + " since directory already exist.")
                continue
            cd_cmd_line = "cd " + local_path + " && "
            # First, clone the repository.
            cmd_line = "git clone"   # Add --progress to include progress info in the log file (note: one line each!)
            remote_name = self.get_optional_setting(repo, "remote-name", "origin")
            if remote_name != "origin" and not clone_args.bare and not clone_args.mirror:
                # bare/mirror and origin are incompatible.
                cmd_line += " --origin " + remote_name
            tag = repo.get_optional_setting("tag")   # Tag can only be in repo.
            if tag is None:
                # Branch.
                remote_branch = self.get_optional_setting(repo, "remote-branch")
                if remote_branch is None:
                    # If a different remote branch is not specified, checkout branch directly in clone command.
                    # Remote branch is also tracked.
                    cmd_line += " --branch " + self.get_mandatory_setting(repo, "branch")
                single_branch = self.get_optional_setting(repo, "single-branch", clone_args.single_branch)
                if single_branch == "yes":
                    cmd_line += " --single-branch"
                elif single_branch == "no":
                    cmd_line += " --no-single-branch"
            depth = self.get_optional_setting(repo, "depth", clone_args.depth)
            if depth is not None:
                cmd_line += " --depth " + str(depth)
            if clone_args.reference is not None:
                # The reference argument must refer to the root of the other project.
                # TODO: Later git versions support --reference-if-able. This is better, if available.
                cmd_line += " --reference " + os.path.join(clone_args.reference, local_path)
            if clone_args.dissociate:
                cmd_line += " --dissociate"
            if clone_args.bare:
                cmd_line += " --bare"
            if clone_args.mirror:
                cmd_line += " --mirror"
            cmd_line += " " + self.get_mandatory_setting(repo, "remote-url") + "/" + repo.get_repo() + ".git"
            cmd_line += " " + local_path
            if args.verbose > 0:
                init_display_line = "Started to clone " + repo.get_repo() + " (" + cmd_line + ")"
            else:
                init_display_line = "Started to clone " + repo.get_repo()
            job.append(Command(cmd_line,
                               init_display_line,
                               "Completed " + repo.get_repo()))
            if not clone_args.bare and not clone_args.mirror:
                # Next, configure the git, if needed.
                remote_push_url = self.get_optional_setting(repo, "remote-push-url")
                if remote_push_url is not None:
                    # Add a different push URL.
                    cmd_line = cd_cmd_line + "git remote set-url --add --push " + remote_name\
                               + " " + remote_push_url + "/" + repo.get_repo() + ".git"
                    job.append(Command(cmd_line))
                    # Finally, checkout the branch, if needed.
                if tag is not None:
                    # Tag name or commit (SHA-1). Just check it out; create no branch.
                    cmd_line = cd_cmd_line + "git checkout " + tag
                    job.append(Command(cmd_line))
                elif remote_branch is not None:
                    # Must use capital -B to force create the branch; needed for example for master,
                    # which is already created by clone above.
                    cmd_line = cd_cmd_line + "git checkout -B " + self.get_mandatory_setting(repo, "branch")\
                               + " " + remote_name + "/" + remote_branch
                    job.append(Command(cmd_line))
            self.queue_job(job)
        # All commands queued up. Gather all remaining results and then cleanup and exit.
        self.finish_commands()
        if not clone_args.no_post_run:
            # Last, execute any bash commands - always in sequence.
            for cmd_line in self.get_run_after_clone_commands():
                # The command line may include single-quotes, but not double-quotes.
                command = Command('bash -c "' + cmd_line + '"')
                command.execute()
                if command.result_output is not None:
                    print(command.result_output, end="")   # NL already included in result output.

    def handle_generic_command_result(self, command):
        """ Handler for generic command results. """
        print("-" * 80)
        print("- " + command.client_data)   # Contains repo name.
        if self.args.verbose > 0:
            print("- Command: " + command.command_line)
        print("-" * 80)
        if command.result_output is not None:
            print(command.result_output, end="")    # NL already included in result output.

    def do_generic(self, args):
        """ Performs a generic git command. Prints the output as is for each target repository. """
        self.set_args(args)
        self.prepare_for_commands()
        for repo in self.get_target_repos(args.groups):
            job = []
            # Determine the local path first, since it is needed for additional commands in the git.
            local_path = repo.get_local_path()
            client_data = local_path
            if args.verbose > 0:
                client_data += " (remote repo: " + repo.get_repo() + ")"
            cd_cmd_line = "cd " + local_path + " && "
            # Execute the git command with the specified arguments.
            cmd_line = cd_cmd_line + "git " + args.command
            cmd_line += " " + " ".join(args.args)
            job.append(Command(cmd_line, None, None, False, args.verbose,
                               self.handle_generic_command_result, client_data))
            self.queue_job(job)
        # All commands queued up. Gather all remaining results and then cleanup and exit.
        self.finish_commands()

    def do_foreach(self, args):
        """ Performs a generic shell command for each target repository.
        Below environment variables are available to the shell/bash command:
        LOCAL_PATH: The local directory path where the repository is stored (OS specific path).
        REMOTE_REPO: The remote repository path.
        REMOTE_NAME: The remote name.
        REMOTE_URL: The remote URL.
        """
        self.set_args(args)
        self.prepare_for_commands()
        for repo in self.get_target_repos(args.groups):
            job = []
            # Determine the local path first, since it is needed for additional commands in the git.
            local_path = repo.get_local_path()
            client_data = local_path
            if args.verbose > 0:
                client_data += " (remote repo: " + repo.get_repo() + ")"
            cd_cmd_line = "cd " + local_path + " && "
            # Execute the bash command with the specified arguments.
            # NOTE: The argument(s) much be quoted, otherwise environment variable expansion
            # happens before this script is invoked. Optimally, only a single quoted argument is provided.
            cmd_line = cd_cmd_line + "LOCAL_PATH=" + local_path + " REMOTE_REPO=" + repo.get_repo()
            cmd_line += " REMOTE_NAME=" + self.get_optional_setting(repo, "remote-name", "origin")
            cmd_line += " REMOTE_URL=" + self.get_mandatory_setting(repo, "remote-url")
            # By using bash -c, the environment variables are valid even if ;, |, && etc. are used.
            cmd_line += " bash -c '" + " ".join(args.args) + "'"
            job.append(Command(cmd_line, None, None, args.verbose,
                               self.handle_generic_command_result, client_data))
            self.queue_job(job)
        # All commands queued up. Gather all remaining results and then cleanup and exit.
        self.finish_commands()

    def handle_snapshot_command_result(self, command):
        """ Handler for snapshot command results. """
        repo = command.client_data
        if command.result_output is not None:
            head_ref = command.result_output[:-1]   # Remove trailing newline character.
            logger.debug("Snapshot for " + repo.get_repo() + ": " + head_ref)
            # Set the HEAD ref as tag in the repo.
            repo.set_setting("tag", head_ref)
            repo.remove_setting("branch")
        # If result_output is None due to error, the error is handled by handle_job_result,
        # so no action here.

    def do_snapshot(self, args):
        """ Creates a new snapshot manifest.
        The snapshot manifest is a copy of the current active manifest expect that for each
        target repo, the current HEAD reference (SHA-1) is inserted as "tag" in the manifest.
        Since tag overrides any branch definition in profiles, the snapshot manifest can be used
        to store the current state. However, keep in mind that if git performs a cleanup,
        the specified HEAD reference may no longer be available. A safer way to make a snapshot is
        to make a tag on each repo instead ("grit tag <tag_name>")
        """
        if len(args.args) == 0:
            # If no specified snapshot file name, create one based on date and time.
            snapshot_file = "snapshot_" + time.strftime("%Y%m%d_%H%M%S")
        else:
            snapshot_file = args.args[0]
        # Base the snapshot manifest on the active manifest.
        snapshot_manifest = Manifest()
        snapshot_manifest.load_active_manifest()
        # Next, fill in the exact ref/commit for each repo.
        self.set_args(args)
        self.prepare_for_commands()
        for repo in snapshot_manifest.get_target_repos(groups=None):
            job = []
            # Determine the local path first, since it is needed for additional commands in the git.
            cd_cmd_line = "cd " + repo.get_local_path() + " && "
            cmd_line = cd_cmd_line + "git rev-parse HEAD"
            job.append(Command(cmd_line, None, None, args.verbose,
                               self.handle_snapshot_command_result, repo))   # repo as client data.
            self.queue_job(job)
        # All commands queued up. Gather all remaining results and then cleanup and exit.
        self.finish_commands()
        snapshot_manifest.save(snapshot_file)


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
        self.config_path = None    # Relative GRIT_DIRECTORY and without ".json". Always using "/" as separator.
        self.active_manifest = None

    def load(self, config_path: str):
        """ Load a new config file. The config_path argument is the path within GRIT_DIRECTORY, except
        that the .json file extension is to be omitted.
        Assumes that current working directory is the project root path.
        """
        self.config_path = config_path
        path_parts = (config_path + ".json").split("/")
        file_path = os.path.join(GRIT_DIRECTORY, *path_parts)
        with open(file_path, "r") as file_stream:
            try:
                self.config = json.load(file_stream,
                                        object_hook=json_config_object_hook)
            except json.JSONDecodeError as err:
                raise JSONDecodeError(str(err) + " in file " + file_path)
        # # Save a small file containing the config file used.
        # with open(os.path.join(GRIT_DIRECTORY, ACTIVE_CONFIG_FILE), "w") as file_stream:
        #     file_stream.write(config)

    def fetch_additional(self):
        """ Fetch any additional manifests. """
        for fetch_manifest in self.get_fetch_manifests():
            if fetch_manifest.get_mandatory_setting("method") == "git":
                repo = fetch_manifest.get_mandatory_setting("repository")
                directory = fetch_manifest.get_optional_setting("directory", repo)   # Default to repo name.
                directory_parts = directory.split("/")
                local_path = os.path.join(*directory_parts)   # Convert to OS specific path.
                if os.path.exists(os.path.join(GRIT_DIRECTORY, local_path)):
                    # Local repo already exist, skip this one silently. For instance, if you update a config file,
                    # only new ones should be cloned.
                    logger.debug("Fetching additional manifests; ignoring " + local_path)
                    continue
                cmd_line = "cd " + GRIT_DIRECTORY + " && git clone"
                branch = fetch_manifest.get_optional_setting("branch")   # Optional.
                if branch is not None:
                    cmd_line += " --branch " + branch
                cmd_line += " " + fetch_manifest.get_mandatory_setting("remote-url") + "/" + repo + ".git"
                cmd_line += " " + local_path
                command = Command(cmd_line, "Fetching additional manifest and config file(s) from " + repo + "...")
                command.execute()
            else:
                raise ValueError("Method " + fetch_manifest["method"] + " is not supported.")

    def update(self):
        """ Update all manifest gits. """
        # TODO: fetch and rebase for branches, but skip for tags/commits, and re-download for ftp/http URLs.
        pass

    def get_manifest_layers(self):
        """ Returns a list of all manifest layers. """
        return self.config["manifest-layers"]

    def get_fetch_manifests(self):
        """ Returns a list of all fetch manifests instructions. """
        return self.config.get("fetch-manifests", [])   # Default to empty list.

    def make_active_manifest(self):
        """ Overlays the specified manifests. """
        # First, create the final manifest.
        self.active_manifest = None
        for manifest_path in self.get_manifest_layers():
            manifest = Manifest()
            # The manifest path is always using "/", regardless of underlying OS.
            if manifest_path.startswith("/"):
                # Path is from root of GRIT_DIRECTORY.
                manifest.load(manifest_path[1:])   # Skip initial "/" since load assumes root of GRIT_DIRECTORY.
            else:
                # Manifest path is relative from directory of config path.
                last_separator_pos = self.config_path.rfind("/")
                if last_separator_pos > 0:
                    manifest.load(self.config_path[:last_separator_pos] + "/" + manifest_path)
                else:
                    manifest.load(manifest_path)
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

    def save_active_manifest(self):
        """ Save the final manifest to the file system. """
        self.active_manifest.save(ACTIVE_MANIFEST_FILE)

    def do_init(self, args):
        init_parser = argparse.ArgumentParser()
        init_parser.add_argument("manifest_url", nargs="?", action="store", default=None)
        init_parser.add_argument("--branch", "-b", action="store", dest="branch", default=None)
        init_parser.add_argument("--directory", "-d", action="store", dest="directory", default=None)
        init_parser.add_argument("--config", "-c", action="store", dest="config", default=None)
        init_parser.add_argument("--manifest", "-m", action="store", dest="manifest", default=None)
        init_parser.add_argument("--update", "-u", action="store_true", dest="update", default=None)
        init_args = init_parser.parse_args(args.args)   # Parse args after init.
        if init_args.update:
            # Update all manifest gits first.
            print("Updating all manifest and config file(s)...")
            self.update()
        # Fetch initial/additional manifest and config file(s), if specified.
        if init_args.manifest_url is not None:
            if not os.path.exists(GRIT_DIRECTORY):
                # Create grit directory if it doesn't exist (=first time).
                cmd_line = "mkdir " + GRIT_DIRECTORY
                command = Command(cmd_line)
                command.execute()
            cmd_line = "cd " + GRIT_DIRECTORY + " && git clone"
            if init_args.branch is not None:
                cmd_line += " --branch " + init_args.branch
            cmd_line += " " + init_args.manifest_url   # Remote URL and repository (including .git).
            if init_args.directory is not None:
                cmd_line += " " + init_args.directory   # TODO: Convert to OS specific path?
            command = Command(cmd_line, "Fetching specified manifest and config file(s)...")
            command.execute()
        # Load and activate a config if specified.
        if init_args.config is not None:
            print("Loading config " + init_args.config + ".")
            self.load(init_args.config)
            self.fetch_additional()
            self.make_active_manifest()
            self.save_active_manifest()
            print("Generated active manifest.")
        elif init_args.manifest is not None:
            print("Loading manifest " + init_args.manifest + ".")
            manifest = Manifest()
            manifest.load(init_args.manifest)
            manifest.save_active_manifest()
            print("Saved as active manifest.")


class Grit(object):
    """ Main grit class for executing commands. """

    def __init__(self):
        self.aliases = None
        self.load_aliases()

    def load_aliases(self):
        """ Load any aliases from user's home directory.
        NOTE: debug mode is enabled after this method is called, so no point in calling logger.debug here.
        """
        file_path = os.path.join(os.path.expanduser("~"), GRIT_ALIASES_FILE)
        try:
            with open(file_path, "r") as file_stream:
                try:
                    self.aliases = json.load(file_stream)
                except json.JSONDecodeError as err:
                    raise JSONDecodeError(str(err) + " in file " + file_path)
        except FileNotFoundError:
            # It is optional to have a grit aliases file.
            pass

    def substitute_aliases(self, string):
        """ Substitutes aliases in the provided string. This is performed using simple text replacements. """
        if self.aliases is not None:
            for alias in self.aliases:
                string = string.replace(alias, self.aliases[alias])
        return string

    def run_command(self, command_line: str):
        """ Runs the grit command with its options and parameters, all provided as a string. """
        parser = argparse.ArgumentParser(prog="grit",
                                         description="grit is a tool to manage many git repositories efficiently"
                                                     " in a project.")
        parser.add_argument("--version", action="version", version="%(prog)s 1.0")
        parser.add_argument("--verbose", "-v", action="count", default=0)
        parser.add_argument("--debug", action="store_true", dest="debug_mode", help="enable debug mode.")
        parser.add_argument("--force", "-f", action="store_true", dest="force_mode",
                            help="continue even if an error occurred.")
        parser.add_argument("--jobs", "-j", type=int, default=1, dest="parallel_jobs",
                            help="number of parallel jobs to perform. Default is 1.")
        parser.add_argument("--no-log", action="store_true", dest="no_log",
                            help="do not add command details to log file.")
        parser.add_argument("--groups", "-g", action="store", dest="groups", default=None,
                            help="a repository must belong to at least one of the listed groups.\n"
                                 "Multiple groups must be comma separated with no space between.")
        parser.add_argument("command", help="command to perform: init, clone, foreach, snapshot, or any git command.")
        parser.add_argument("args", help="arguments to the command (depends on command)", nargs=argparse.REMAINDER)
        command_line = self.substitute_aliases(command_line)
        args = parser.parse_args(command_line.split(" "))
        if args.debug_mode:
            logging.basicConfig(level=logging.DEBUG)
            logger.debug("Enabled debug mode.")
            logger.debug("Running command " + command_line)
        else:
            logger.setLevel(logging.ERROR)
        if args.command == "init":   # init must be called from the project root directory (=parent of GRIT_DIRECTORY).
            config = Config()
            config.do_init(args)
        else:
            manifest = Manifest()
            manifest.load_active_manifest()
            if args.command == "clone":
                manifest.do_clone(args)
            elif args.command == "foreach":
                manifest.do_foreach(args)
            elif args.command == "snapshot":
                manifest.do_snapshot(args)
            else:
                # Assume a git command. Note that local git aliases also will work.
                manifest.do_generic(args)


if __name__ == "__main__":
    Grit().run_command(" ".join(sys.argv[1:]))
