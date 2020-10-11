import json
from datetime import datetime as dt
from typing import List, Tuple, Dict, Any, Optional
from .utils import run_cmd, CABError, parse_datetime
from .container_image import ContainerImageName, ContainerImage


class PodmanError(CABError):
    def __init__(self, rc: int, msg: str):
        super().__init__(rc, msg)


def raise_podman_error(rc: int, msg: Any) -> None:
    raise PodmanError(rc, msg)


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
