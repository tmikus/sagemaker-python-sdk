import logging
import os.path
from os.path import abspath, realpath, dirname, normpath, join as joinpath
import re
import subprocess
import tarfile


logger = logging.getLogger(__name__)

PIGZ_COMMAND = "pigz"
TAR_COMMAND = "tar"


class FileToCompress:
    def __init__(self, file_path: str, arcname: str = None):
        self.file_path = file_path
        self.arcname = arcname

    def get_transform(self) -> str:
        if self.arcname is None:
            return ""
        if self.arcname == os.path.sep:
            self.arcname = ""
        if _is_bsd_tar():
            return f"-s \"/^{re.escape(self.file_path)}/{re.escape(self.arcname)}/\""
        return f"--transform \"s|^{re.escape(self.file_path)}|{re.escape(self.arcname)}|\""

    def has_transform(self) -> bool:
        return self.arcname is not None


def compress_files_to_tar_gz(
    archive_path: str,
    files: list[FileToCompress],
):
    if _command_exists(TAR_COMMAND):
        transforms = " ".join([file.get_transform() for file in files if file.has_transform()])
        files = " ".join([file.file_path for file in files])
        if _command_exists(PIGZ_COMMAND):
            compress_command = f"-c --use-compress-program={PIGZ_COMMAND} -f"
        else:
            compress_command = "-czf"
        command_text = f"{TAR_COMMAND} {compress_command} {archive_path} {transforms} {files}"
        subprocess.run(command_text, shell=True, check=True, text=True, capture_output=True)
    else:
        with tarfile.open(archive_path, mode="w:gz", dereference=True) as t:
            for file in files:
                # Add all files from the directory into the root of the directory structure of the tar
                t.add(file.file_path, arcname=file.arcname)

def extract_tar_gz(
    archive_path: str,
    destination_path: str,
):
    if _command_exists(TAR_COMMAND):
        if _command_exists(PIGZ_COMMAND):
            command_text = f"{PIGZ_COMMAND} -dc {archive_path} | {TAR_COMMAND} xf - -C {destination_path}"
        else:
            command_text = f"{TAR_COMMAND} -xzf {archive_path} -C {destination_path}"

        subprocess.run(command_text, shell=True, check=True, text=True, capture_output=True)
    else:
        with tarfile.open(name=archive_path, mode="r:gz") as t:
            custom_extractall_tarfile(t, destination_path)

def custom_extractall_tarfile(tar, extract_path):
    """Extract a tarfile, optionally using data_filter if available.

    # TODO: The function and it's usages can be deprecated once SageMaker Python SDK
    is upgraded to use Python 3.12+

    If the tarfile has a data_filter attribute, it will be used to extract the contents of the file.
    Otherwise, the _get_safe_members function will be used to filter bad paths and bad links.

    Args:
        tar (tarfile.TarFile): The opened tarfile object.
        extract_path (str): The path to extract the contents of the tarfile.

    Returns:
        None
    """
    if hasattr(tarfile, "data_filter"):
        tar.extractall(path=extract_path, filter="data")
    else:
        tar.extractall(path=extract_path, members=_get_safe_members(tar))

def _command_exists(command: str) -> bool:
    exit_code, _ = subprocess.getstatusoutput(f"command -v {command}")
    return exit_code == 0


def _is_bsd_tar() -> bool:
    _, output = subprocess.getstatusoutput("tar --version")
    return output.startswith("bsdtar ")


def _get_safe_members(members):
    """A generator that yields members that are safe to extract.

    It filters out bad paths and bad links.

    Args:
        members (list): A list of members to check.

    Yields:
        tarfile.TarInfo: The tar file info.
    """
    base = _get_resolved_path(".")

    for file_info in members:
        if _is_bad_path(file_info.name, base):
            logger.error("%s is blocked (illegal path)", file_info.name)
        elif file_info.issym() and _is_bad_link(file_info, base):
            logger.error("%s is blocked: Symlink to %s", file_info.name, file_info.linkname)
        elif file_info.islnk() and _is_bad_link(file_info, base):
            logger.error("%s is blocked: Hard link to %s", file_info.name, file_info.linkname)
        else:
            yield file_info


def _is_bad_link(info, base):
    """Checks if the link is rooted under the base directory.

    Ensuring that the link does not attempt to access paths outside the expected directory structure

    Args:
        info (tarfile.TarInfo): The tar file info.
        base (str): The base directory.

    Returns:
        bool: True if the link is not rooted under the base directory, False otherwise.
    """
    # Links are interpreted relative to the directory containing the link
    tip = _get_resolved_path(joinpath(base, dirname(info.name)))
    return _is_bad_path(info.linkname, base=tip)

def _get_resolved_path(path):
    """Return the normalized absolute path of a given path.

    abspath - returns the absolute path without resolving symlinks
    realpath - resolves the symlinks and gets the actual path
    normpath - normalizes paths (e.g. remove redudant separators)
    and handles platform-specific differences
    """
    return normpath(realpath(abspath(path)))


def _is_bad_path(path, base):
    """Checks if the joined path (base directory + file path) is rooted under the base directory

    Ensuring that the file does not attempt to access paths
    outside the expected directory structure.

    Args:
        path (str): The file path.
        base (str): The base directory.

    Returns:
        bool: True if the path is not rooted under the base directory, False otherwise.
    """
    # joinpath will ignore base if path is absolute
    return not _get_resolved_path(joinpath(base, path)).startswith(base)
