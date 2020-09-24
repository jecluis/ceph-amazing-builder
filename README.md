ceph amazing builder
--------------------

TBD - but we aim at building ceph sources, and ending up with a container for
said build.


container/storage.conf paths need to be on btrfs, otherwise it's going to fail
miserably. Additionally, seems it might need quite a lot of space for the
humongous images.

