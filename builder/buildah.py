import errno
from pathlib import Path
from typing import List, Tuple, Any, Optional
from .utils import run_cmd, pdebug, CABError


class BuildahError(CABError):
    def __init__(self, rc: int, msg: str):
        super().__init__(rc, msg)


def raise_buildah_error(rc: int, msg: Any) -> None:
    raise BuildahError(rc, msg)


class Buildah:

    _from: str
    _wc: Optional[str]  # working container
    _mount_path: Optional[Path] = None
    _committed: bool = False
    _hashid: Optional[str] = None
    _name: Optional[str] = None

    def __init__(self, _from: str):
        self._from = _from
        self._wc = None
        self._create()
        self._committed = False

    def is_committed(self):
        return self._committed

    def is_ready(self) -> bool:
        return self._wc is not None

    def get_working_container(self):
        return self._wc

    def get_hashid(self):
        return self._hashid

    def get_name(self):
        return self._name

    def _create(self):
        assert not self.is_committed()
        assert not self.is_ready()
        assert self._from is not None
        assert len(self._from) > 0

        self.debug(f"creating from {self._from}")
        cmd = f"from {self._from}"
        ret, stdout, stderr = self._run(cmd)
        if ret != 0:
            raise_buildah_error(ret, stderr)
        if len(stdout) < 1:
            raise_buildah_error(ret, stderr)
        self._wc = stdout[0]
        assert self._wc and len(self._wc) > 0

    def _run(self,
             cmd: str,
             capture_output: bool = True
             ) -> Tuple[int, List[str], List[str]]:
        """ Run buildah command """
        buildah_cmd = f"buildah unshare buildah {cmd}"
        return run_cmd(buildah_cmd,
                       capture_output=capture_output)

    def run(self, cmd: str,
            capture_output: bool = True,
            volumes: Optional[List[Tuple[str, str]]] = None
            ) -> Tuple[int, List[str]]:
        """ Run command in container. """
        assert self.is_ready()
        volstr = ""
        if volumes:
            volstr = ' '.join([f"-v {src}:{dest}" for src, dest in volumes])
        _cmd: str = f"run {volstr} {self._wc} -- {cmd}"
        ret, stdout, stderr = self._run(_cmd, capture_output=capture_output)
        if ret != 0:
            return ret, stderr
        return ret, stdout

    def mount(self) -> Path:
        assert not self.is_committed()
        assert self.is_ready()
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
        assert self.is_ready()
        if not self._mount_path:
            return  # be idempotent
        ret, _, stderr = self._run(f"unmount {self._wc}")
        if ret != 0:
            raise_buildah_error(ret, stderr)
        self._mount_path = None

    def commit(self, _name: str, _tag: str = None) -> str:
        name: str = _name if not _tag else f"{_name}:{_tag}"
        self.debug(f"committing working container {self._wc} as {name}")
        assert not self.is_committed()
        assert self.is_ready()
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
        assert self.is_ready()
        self.debug(f"tagging {self._name} with {tag}")
        cmd = f"tag {self._hashid} {self._name}:{tag}"
        ret, _, stderr = self._run(cmd)
        if ret != 0:
            raise_buildah_error(ret, stderr)

    def config(self, confstr: str):
        assert not self.is_committed()
        assert self.is_ready()
        assert confstr is not None and len(confstr) > 0
        self.debug(f"set config '{confstr}'")
        ret, _, stderr = self._run(f"config {confstr} {self._wc}")
        if ret != 0:
            raise_buildah_error(ret, stderr)

    def set_label(self, key: str, value: str):
        assert self.is_ready()
        assert key is not None and len(key) > 0
        assert value is not None and len(value) > 0
        self.debug(f"set label {key} = {value}")
        self.config(f"--label {key}='{value}'")

    def set_author(self, name: str, email: str):
        assert self.is_ready()
        author: str = f"{name} <{email}>"
        self.debug(f"set author {author}")
        self.set_label("author", author)

    def change_workdir(self, wdir: str):
        assert self.is_ready()
        assert wdir is not None and len(wdir) > 0
        self.debug(f"change workdir to '{wdir}'")
        self.config("--workdir {wdir}")

    def debug(self, logstr):
        pdebug("buildah(from {}): {}".format(
            self._from, logstr
        ))
