from pathlib import Path
from typing import List, Optional
from .utils import pwarn, perror, pinfo
from .container_image import ContainerImage, ContainerImageName
from .podman import Podman
from .buildah import Buildah


class Images:
    def __init__(self):
        pass

    """
    We have five kinds of images:
        - seed image, which is shared by all images there are, and essentially
        is setup so that we minimize work across vendor images;
        - builder image, which is an image with the build dependencies
        installed for a given release version for a specific vendor;
        - base image, which is an image with all known packages that might
        be needed to run the resulting build, for a given release and vendor;
        - build's raw image, which is essentially a release image with the
        resulting binaries from a build;
        - build's image, which is the build's raw image with adjusted
        permissions and whatever else that might be needed.

    """

    @classmethod
    def has_seed_image(cls) -> bool:
        return cls.find_seed_image() is not None

    @classmethod
    def has_base_image(cls, vendor: str, release: str) -> bool:
        return cls.find_base_image(vendor, release) is not None

    @classmethod
    def has_builder_image(cls, vendor: str, release: str) -> bool:
        return cls.find_builder_image(vendor, release) is not None

    @classmethod
    def find_seed_image(cls) -> Optional[ContainerImage]:
        images_lst: List[ContainerImage] = \
            Podman.get_images("cab/seed/suse:leap-15.2")

        image: ContainerImage
        for image in images_lst:
            name: ContainerImageName
            for name in image.names:
                if name.name == "suse" and name.tag == "leap-15.2":
                    return image
        return None

    @classmethod
    def find_builder_image(
        cls,
        vendor: str,
        release: str
    ) -> Optional[ContainerImage]:
        images_lst: List[ContainerImage] = \
            Podman.get_images(f"cab/builder/{vendor}:{release}")

        image: ContainerImage
        for image in images_lst:
            name: ContainerImageName
            for name in image.names:
                if name.name == vendor and name.tag == release:
                    return image
        return None

    @classmethod
    def find_base_image(
        cls,
        vendor: str,
        release: str
    ) -> Optional[ContainerImage]:
        images_lst: List[ContainerImage] = \
            Podman.get_images(f"cab/base/{vendor}:{release}")

        image: ContainerImage
        for image in images_lst:
            # get the first one matching, so we can get a hashid
            name: ContainerImageName
            for name in image.names:
                if name.name == vendor and \
                   name.tag == release and \
                   name.repository == "cab/base":
                    return image
        return None

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


class ImageBuilder:

    @classmethod
    def build_seed_image(cls, force=False) -> str:

        if Images.has_seed_image() and not force:
            return 'cab/seed/suse:leap-15.2'

        working_container = Buildah('opensuse/leap:15.2')
        working_container.set_author("Joao Eduardo Luis", "joao@suse.com")
        working_container.run("zypper --gpg-auto-import-keys refresh")
        working_container.run("zypper -n install git sudo wget ccache")
        hashid = working_container.commit("cab/seed/suse", "leap-15.2")
        return hashid

    @classmethod
    def build_base_image(cls,
                         vendor: str, release: str,
                         sourcepath: Path,
                         binpath: Path) -> str:
        pinfo(f"=> building base image for vendor {vendor} release {release}")

        assert binpath.exists()
        assert binpath.is_dir()
        assert binpath.joinpath("install-requirements.sh").exists()
        print(f"binpath: {binpath}")
        print(f"sourcepaht: {sourcepath}")

        # assume base suse image exists for now
        working_container = Buildah('cab/seed/suse:leap-15.2')
        # Assume that's me for now.
        # We should make this configurable, or infer from something?
        working_container.set_author("Joao Eduardo Luis", "joao@suse.com")
        working_container.set_label("cab.ceph-vendor", vendor)
        working_container.set_label("cab.cab-release", release)

        working_container.run("mkdir -p /build/sources")
        working_container.run("mkdir -p /build/bin")
        working_container.config("--workingdir /build/sources")
        working_container.run("/bin/bash ./install-deps.sh",
                              volumes=[(str(sourcepath), "/build/sources")],
                              capture_output=False)
        working_container.run(
                "/bin/bash /build/bin/install-requirements.sh",
                volumes=[
                    (str(binpath), "/build/bin"),
                    (str(sourcepath), "/build/sources")
                ], capture_output=False)
        working_container.config("--workingdir /")
        working_container.run("rm -fr /build")

        image_name = f"cab/base/{vendor}"
        image_name_tagged = f"{image_name}:{release}"
        hashid = working_container.commit(image_name, release)
        pinfo(f"=> container image {image_name_tagged} ({hashid[:12]})")
        return hashid

    @classmethod
    def build_builder_image(cls, vendor: str, release: str) -> str:
        pinfo(
            f"=> building builder image for vendor {vendor} release {release}")

        working_container = Buildah(f'cab/base/{vendor}:{release}')
        working_container.set_author("Joao Eduardo Luis", "joao@suse.com")

        working_container.run("mkdir -p /build")
        working_container.run("useradd -d /build builder")
        working_container.run("chown builder:users /build")
        working_container.config("--user builder:users")
        working_container.run("mkdir -p /build/src")
        working_container.run("mkdir -p /build/ccache")
        working_container.run("mkdir -p /build/bin")
        working_container.run("mkdir -p /build/out")
        working_container.config("--workingdir /build")
        volume_str = \
            '"/build/src","/build/ccache","/build/bin","/build/out"'
        working_container.config(f"--volume {volume_str}")
        entrypoint = '"/build/bin/entrypoint.sh"'
        working_container.config(f"--entrypoint {entrypoint}")

        hashid = working_container.commit(f"cab/builder/{vendor}", release)
        return hashid


class ImageChecker:

    @classmethod
    def check_create_seed_image(cls) -> bool:
        image: Optional[ContainerImage] = Images.find_seed_image()
        if image:
            pinfo("=> seed image exists.")
            return True

        pinfo("=> creating seed image...")
        if ImageBuilder.build_seed_image():
            pinfo("=> created seed image")
            return True
        else:
            perror("=> error creating seed image")
            return False

    @classmethod
    def check_create_base_image(
            cls,
            vendor: str,
            release: str,
            sourcepath: Path,
            binpath: Path
    ) -> bool:

        image: Optional[ContainerImage] = \
            Images.find_base_image(vendor, release)
        if image:
            pinfo("=> base image exists.")
            return True

        pinfo(f"=> creating base image for vendor {vendor} release {release}")
        assert binpath.exists()
        assert binpath.is_dir()

        if ImageBuilder.build_base_image(vendor, release, sourcepath, binpath):
            pinfo("=> created base image for "
                  f"vendor {vendor} release {release}")
            return True
        else:
            perror("=> error creating base image for "
                   f"vendor {vendor} release {release}")
            return False

    @classmethod
    def check_create_builder_image(cls, vendor: str, release: str) -> bool:

        image: Optional[ContainerImage] = \
            Images.find_builder_image(vendor, release)
        if image:
            pinfo("=> builder image exists.")
            return True

        pinfo("=> creating builder image for "
              f"vendor {vendor} release {release}")
        if ImageBuilder.build_builder_image(vendor, release):
            pinfo("=> created builder image for "
                  f"vendor {vendor} release {release}")
            return True
        else:
            perror("=> error creating builder image for "
                   f"vendor {vendor} release {release}")
            return False

    @classmethod
    def check_create_images(
            cls,
            vendor: str,
            release: str,
            sourcepath: Path,
            binpath: Path
    ) -> bool:

        pinfo("=> checking images availability...")
        if not cls.check_create_seed_image():
            perror("=> seed image does not exist!")
            return False

        cls.check_create_base_image(vendor, release, sourcepath, binpath)
        cls.check_create_builder_image(vendor, release)
        return True

    @classmethod
    def check_has_images(cls, vendor: str, release: str) -> bool:
        if not Images.has_seed_image():
            return False
        if not Images.has_base_image(vendor, release):
            return False
        if not Images.has_builder_image(vendor, release):
            return False
        return True
