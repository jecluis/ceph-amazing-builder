import subprocess
import shlex
import sys
import os
import errno
from pathlib import Path
from typing import List, Tuple, Any
from .utils import serror, run_cmd, pdebug


class BuildahError(Exception):
	pass


def raise_buildah_error(rc: int, msg: Any):
	_err: str = os.strerror(rc)
	_msg: str = ""
	if isinstance(msg, list):
		_msg = '\n'.join(msg)
	elif isinstance(msg, str):
		_msg = msg
	if len(_msg) > 0:
		_err += f": {_msg}"
	raise BuildahError(serror(_err))


class Buildah:

	_from: str = None
	_wc: str = None	# working container
	_mount_path: Path = None
	_committed: bool = False
	_hashid: str = None
	_name: str = None

	def __init__(self, _from: str):
		self._create_from(_from)
		self._committed = False


	def is_committed(self):
		return self._committed


	def get_working_container(self):
		return self._wc


	def get_hashid(self):
		return self._hashid


	def get_name(self):
		return self._name


	def _create_from(self, img):
		assert not self.is_committed()

		self.debug(f"creating from {img}")
		cmd = f"from {img}"
		ret, stdout, stderr = self._run(cmd)
		if ret != 0:
			raise_buildah_error(ret, stderr)
		if len(stdout) < 1:
			raise_buildah_error(ret, stderr)
		self._from = img
		self._wc = stdout[0]
		assert self._wc and len(self._wc) > 0

	
	def _run(self,
	         cmd: str,
	         capture_output: bool = True
	) -> Tuple[int, List[str], List[str]]:
		""" Run buildah command """
		buildah_cmd = f"buildah unshare buildah {cmd}"
		return run_cmd(buildah_cmd, capture_output=capture_output)


	def run(self, cmd, capture_output: bool = True) -> Tuple[int, List[str]]:
		""" Run command in container. """
		_cmd: str = f"run {self._wc} {cmd}"
		ret, stdout, stderr = self._run(_cmd, capture_output=capture_output)
		if ret != 0:
			return ret, stderr
		return ret, stdout
		

	def mount(self) -> Path:
		assert not self.is_committed()
		assert self._wc is not None
		assert len(self._wc) > 0
		self.debug(f"mounting working container {self._wc}")
		ret, stdout, stderr = self._run(f"mount {self._wc}")
		if ret != 0:
			raise_buildah_error(ret, stderr)
		if not stdout or len(stdout) < 1:
			raise_buildah_error(ret, stderr)
		mnt = stdout[0]
		assert mnt is not None and len(mnt) > 0
		self._mount_path = Path(mnt).expanduser().absolute()
		if not self._mount_path.exists():
			raise_buildah_error(errno.ENOENT, mnt)
		elif not self._mount_path.is_dir():
			raise_buildah_error(errno.ENOTDIR, mnt)
		return self._mount_path


	def unmount(self):
		self.debug(f"unmounting working container {self._wc}")
		assert not self.is_committed()
		if not self._mount_path:
			return # be idempotent
		ret, _, stderr = self._run(f"unmount {self._wc}")
		if ret != 0:
			raise_buildah_error(ret, stderr)
		self._mount_path = None


	def commit(self, _name: str, _tag: str = None) -> str:
		name: str = _name if not _tag else f"{_name}:{_tag}"
		self.debug(f"committing working container {self._wc} as {name}")
		assert not self.is_committed()
		assert self._wc is not None
		assert len(self._wc) > 0
		assert name is not None
		assert len(name) > 0

		ret, stdout, stderr = self._run(f"commit {self._wc} {name}")
		if ret != 0:
			raise_buildah_error(ret, stderr)
		if not stdout or len(stdout) < 1:
			raise_buildah_error(ret, stderr)
		hashid = stdout[0]
		assert hashid is not None
		assert len(hashid) > 0
		self._committed = True
		self._hashid = hashid
		self._name = _name
		return hashid


	def tag(self, tag: str):
		assert self.is_committed()
		self.debug(f"tagging {self._name} with {tag}")
		cmd = f"tag {self._hashid} {self._name}:{tag}"
		ret, _, stderr = self._run(cmd)
		if ret != 0:
			raise_buildah_error(ret, stderr)


	def debug(self, logstr):
		pdebug("buildah(from {}): {}".format(
			self._from, logstr
		))