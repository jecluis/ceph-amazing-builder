import click
import json
import re
from typing import List, Tuple, Optional, Dict, Any, TypeVar
from datetime import datetime as dt
from .utils import run_cmd, CABError, pwarn, perror


# from
#  https://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
# because I'm lazy.
def sizeof_fmt(num, suffix='B') -> str:
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def parse_datetime(datestr: str) -> dt:
    # podman returns timestamps that python has a hard time handling.
    # make it easier by discarding some precision.
    m = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*', datestr)
    assert m is not None
    assert len(m.groups()) > 0
    assert len(m.group(1)) > 0
    return dt.fromisoformat(m.group(1))


class PodmanError(CABError):
    def __init__(self, rc: int, msg: str):
        super().__init__(rc, msg)


def raise_podman_error(rc: int, msg: Any) -> None:
    raise PodmanError(rc, msg)


T_CIN = TypeVar('T_CIN', bound='ContainerImageName')


class ContainerImageName:
    _remote: str
    _repo: str
    _name: str
    _tag: str

    def __init__(self, remote: str, repo: str, name: str, tag: str):
        self._remote = remote
        self._repo = repo
        self._name = name
        self._tag = tag

    @property
    def name(self) -> str:
        return self._name

    @property
    def tag(self) -> str:
        return self._tag

    @property
    def repository(self) -> str:
        return self._repo

    def __str__(self) -> str:
        return f"{self._remote}/{self._repo}/{self._name}:{self._tag}"

    @classmethod
    def parse(cls: T_CIN, namestr: str) -> Optional[T_CIN]:
        if not namestr or len(namestr) == 0:
            return None

        matchstr = r"^([-._\d\w]+)/(.*)/([-_\d\w]+):([-_\d\w]+)$"
        match = re.match(matchstr, namestr)
        if not match:
            return None
        if len(match.groups()) < 4:
            return None

        remote: str = match.group(1)
        repo: str = match.group(2)
        img_name: str = match.group(3)
        tag: str = match.group(4)
        return cls(remote, repo, img_name, tag)


class ContainerImage:
    _hashid: str
    _name: str
    _names: List[ContainerImageName]
    _tags: List[str]
    _size: float
    _created: dt

    def __init__(self, hashid: str,
                 names: List[ContainerImageName], size: float, created: dt):
        self._hashid: str = hashid
        self._names: List[ContainerImageName] = names
        self._tags: List[str] = self._get_tags()
        self._size: float = size
        self._created: dt = created

    def _get_tags(self) -> List[str]:
        tags: List[str] = []
        name: ContainerImageName
        for name in self._names:
            tags.append(name._tag)
        return tags

    def has_tag(self, tag: str) -> bool:
        return tag in self._tags

    def print(self) -> None:
        latest: str = ""
        if 'latest' in self._tags:
            latest = click.style("(latest)", fg="yellow")
        print("{} {} ({}) {}".format(
            click.style("- id:", fg="cyan"),
            self._hashid,
            sizeof_fmt(self._size), latest))
        for name in self._names:
            print("{} {}".format(click.style("  - name:", fg="cyan"), name))
        print("{} {}".format(
              click.style("  - created:", fg="cyan"),
              self._created))

    def __str__(self) -> str:
        return f"{self._hashid} {self._names}"

    def get_latest_name(self) -> Optional[str]:
        name: Optional[ContainerImageName] = self.get_latest_image_name()
        if name:
            return str(name)
        return None

    def get_latest_image_name(self) -> Optional[ContainerImageName]:
        name: ContainerImageName
        for name in self._names:
            if name.tag == "latest":
                return name
        return None

    @property
    def size(self) -> float:
        return self._size

    def get_size_str(self) -> str:
        return sizeof_fmt(self._size)

    @property
    def created(self) -> dt:
        return self._created

    @property
    def names(self) -> List[ContainerImageName]:
        return self._names

    @property
    def hashid(self) -> str:
        return self._hashid

    @property
    def short_hashid(self) -> str:
        return self._hashid[:12]


class Podman:

    @classmethod
    def _run(cls,
             _cmd: str,
             capture_output: bool = True
             ) -> Tuple[int, List[str]]:
        cmd = f"podman {_cmd}"
        ret, stdout, stderr = run_cmd(cmd, capture_output=capture_output)
        if ret != 0:
            return ret, stderr
        return ret, stdout

    @classmethod
    def get_images_raw(cls, name: Optional[str] = None) -> List[Any]:
        cmd = "images --format json"
        if name:
            cmd += f" {name}"
        ret, result = cls._run(cmd)
        if ret != 0:
            raise_podman_error(ret, result)
        return json.loads('\n'.join(result))

    @classmethod
    def get_images(cls, _filter: Optional[str] = None) -> List[ContainerImage]:
        cmd = "images --format json"
        if _filter:
            cmd += f" {_filter}"
        ret, result = cls._run(cmd)
        if ret != 0:
            raise_podman_error(ret, result)

        images_lst: List[Dict[Any, Any]] = json.loads('\n'.join(result))
        images: List[ContainerImage] = []
        obtained_images: List[str] = []
        for entry in images_lst:
            hashid: str = entry['Id']
            created: dt = parse_datetime(entry['CreatedAt'])
            size: int = entry['Size']
            if hashid in obtained_images:
                continue
            names: List[str] = []
            name: str
            for name in entry['Names']:
                n = ContainerImageName.parse(name)
                if n is None:
                    continue  # not one of our images, probably.
                names.append(n)
            images.append(ContainerImage(hashid, names, size, created))

        return images

    @classmethod
    def run(cls,
            image: str,
            cmd: str,
            capture_output: bool = True,
            interactive: bool = False) -> Tuple[int, List[str]]:
        _cmd: str = "run {it} {image} {cmd}"
        it: str = "-it" if interactive else ""
        return cls._run(_cmd.format(it=it, image=image, cmd=cmd),
                        capture_output=capture_output)

    @classmethod
    def remove_image(cls, image: str) -> Tuple[int, List[str]]:
        return cls._run(f"rmi {image}", capture_output=True)


class Containers:
    def __init__(self):
        pass

    @classmethod
    def find_base_build_image(cls, vendor: str, release: str) -> Optional[str]:
        images_lst: List[ContainerImage] = \
            Podman.get_images(f"cab/build/{vendor}:{release}")

        image: ContainerImage
        for image in images_lst:
            for name in image.names:
                if name.name == vendor and name.tag == release:
                    return str(name)
        return None

    @classmethod
    def find_release_base_image(
        cls,
        vendor: str,
        release: str
    ) -> Tuple[Optional[str], Optional[str]]:
        images_lst: List[ContainerImage] = \
            Podman.get_images(f"cab/base/release/{vendor}:{release}")

        image: ContainerImage
        for image in images_lst:
            # get the first one matching, so we can get a hashid
            name: ContainerImageName
            for name in image.names:
                if name.name == vendor and \
                   name.tag == release and \
                   name.repository == "cab/base/release":
                    return str(name), image.hashid
        return None, None

    @classmethod
    def find_build_images(cls, buildname="") -> List[ContainerImage]:
        images_lst: List[ContainerImage] = \
            Podman.get_images(f"cab-builds/{buildname}")

        hashids: List[str] = []
        images: List[ContainerImage] = []
        image: ContainerImage
        for image in images_lst:
            is_match: bool = False
            for name in image.names:
                if name.name != buildname:
                    continue
                is_match = True
                break
            if is_match and image.hashid not in hashids:
                hashids.append(image.hashid)
                images.append(image)
        return images

    @classmethod
    def find_build_image_latest(cls, name: str) -> Optional[ContainerImage]:
        return cls.find_build_image(name, "latest")

    @classmethod
    def find_build_image(cls,
                         name: str,
                         tag="latest"
                         ) -> Optional[ContainerImage]:
        imgs: List[ContainerImage] = cls.find_build_images(name)
        for image in imgs:
            if image.has_tag(tag):
                return image
        return None

    @classmethod
    def has_build_image(cls, name: str, tag="latest") -> bool:
        return cls.find_build_image(name, tag) is not None

    @classmethod
    def run_shell(cls, name: str) -> bool:
        latest: Optional[ContainerImage] = cls.find_build_image_latest(name)
        if not latest:
            return False
        Podman.run(latest.hashid, "/bin/bash",
                   interactive=True, capture_output=False)
        return True

    @classmethod
    def rm_image(cls, image: ContainerImage) -> bool:
        success = True
        pwarn(f"=> remove image id {image.hashid}")
        name: ContainerImageName
        for name in image.names:
            pwarn(f"  - remove {name}")
            ret, result = Podman.remove_image(str(name))
            if ret != 0:
                perror(f"error removing container image {name}")
                perror('\n'.join(result))
                success = False
                continue
        return success

    @classmethod
    def get_build_name(cls, buildname: str) -> str:
        return f"cab-builds/{buildname}"

    @classmethod
    def get_build_name_latest(cls, buildname: str) -> Optional[str]:
        img: Optional[ContainerImage] = cls.find_build_image_latest(buildname)
        if not img:
            return None
        return img.get_latest_name()
