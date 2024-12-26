# genTree

genTree generates a filesystem tree in a namespace using portage.

## Usage

`genTree-import-seed <system root> <seed name> [conf_root]`

* `system root` - The system root to import, can be a stage3 tarball or a directory.
* `seed name` - The seed name to use.
* `conf_root` - Alternate configuration root to use.

> The `conf_root` is `~/.local/share/genTree` by default

ex. `genTree-import-seed stage3.tar.xz stage3-openrc .`

> The first argument is the SYROOT target

`genTree config.toml`

## Configuration

Example configuration file:

```
# nginx.toml

# name = "nginx"  # The name is set to the filename without extension by default
# output_file = "nginx.tar"  # The output file is set to the name with a .tar extension by default

# A seed must be defined
seed = "stage3-openrc"

# profile = "default/linux/amd64/23.0"  # Set the profile

bases = ["tini", "gcc"]

use = "nginx"
packages = ["www-servers/nginx"]
unmerge = ["sys-devel/gcc"]

tar_filter_vardbpkg = true
```

* `packages` (list) - The packages to emerge.
* `unmerge` (list) - The packages to unmerge.
* `deplean` (false) - Run depclean --with-bdeps=n after emerging.

### Bases

Bases are configurations used as a base for another config.

Bases layer contents are extracted to the lower_dir of the build layer's overlayfs mount.

> Builtin bases such as `tini`, `glibc`, and `base` can be specified without a suffix to be used

### Tar flters

Several filters are available for use when packing layer tarballs:

* `tar_filter_whiteouts` (true) - Filters OCI whiteouts. (.wh. files)
* `tar_filter_dev` (true) - Filters character and block devices.
* `tar_filter_man` (true) - Filters man pages.
* `tar_filter_docs` (true) - Filters documentation.
* `tar_filter_include` (false) - Filters headers/includes.
* `tar_filter_charmaps` (true) - Filters charmaps.
* `tar_filter_completions` (true) - Filters locales.
* `tar_filter_vardbpkg` (false) - Filters `/var/db/pkg`.

### Profile

The profile can be set using:

* `profile` (default/linux/amd64/23.0) - The profile to use.
* `profile_repos` (gentoo) - The repository source for the profile.

### Portage Environment Variables

Portage environment variables can be set in the configuration file:

* `use` (set/list) - USE flags to set.
* `features` (set/list) - FEATURES to set.
* `binpkg_format` (gpkg) - The binary package format to use.

> The `use` and `features` variables are sets which can interpret adding and removing flags using `+` and `-` prefixes.

## Mounts

Several components are mounted into the build namespace as read-only bind mounts:

* `bind_system_repos` (true) - mounts the path `system_repos` to `/var/db/repos`.

### Config overlay

Configuration overrides to be mounted over `/etc/portage` can be specified using:

* `config_overlay` (str) - The name of the configuration overlay to use (from `config_dir`).

### Build overlay

The build are performed in overlays which are mounted over `/builds` in the namespace, and under `conf_root`/builds on the host.

> `conf_root` is ~/.local/share/genTree by default

The upper_dir is used to build layers between stages, and the mount point is used for the outermost layer.

