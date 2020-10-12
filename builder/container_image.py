import re
from datetime import datetime as dt
from typing import TypeVar, Optional, List
from .utils import swarn, sinfo, sizeof_fmt


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

        matchstr = r"^([-._\d\w]+)/(.*)/([-_\d\w]+):([-._\d\w]+)$"
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
            latest = swarn("(latest)")
        print("{} {} ({}) {}".format(
            sinfo("- id:"),
            self._hashid,
            sizeof_fmt(self._size), latest))
        for name in self._names:
            print("{} {}".format(sinfo("  - name:"), name))
        print("{} {}".format(
              sinfo("  - created:"),
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

    def get_real_name(self, name: str, tag="latest") -> Optional[str]:
        for n in self.names:
            if n.name == name and n.tag == tag:
                return str(n)
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
