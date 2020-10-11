from typing import List, Tuple, Optional
from .utils import pwarn, perror
from .container_image import ContainerImage, ContainerImageName
from .podman import Podman


class Images:
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
