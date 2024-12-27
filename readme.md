# genTree

genTree generates a filesystem tree in a namespace using portage.

## Usage

`genTree-import-seed <system root> <seed name> [conf_root]`

* `system root` - The system root to import, can be a stage3 tarball or a directory.
* `seed name` - The seed name to use.
* `conf_root` - Alternate configuration root to use.

> The `conf_root` is `~/.local/share/genTree` by default

ex. `genTree-import-seed stage3.tar.xz stage3-openrc .`

`genTree <config file> [--debug, -d]`

ex. `genTree nginx.toml`

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

[clean_filter_options]
charmaps = true  # Delete charmaps before packing

[tar_filter_options]
locales = true # Filter locales when packing
```

* `packages` (list) - The packages to emerge.
* `unmerge` (list) - The packages to unmerge.
* `deplean` (false) - Run depclean --with-bdeps=n after emerging.

### Bases

Bases are configurations used as a base for another config.

Bases layer contents are extracted to the lower_dir of the build layer's overlayfs mount.

> Builtin bases such as `tini`, `glibc`, and `base` can be specified without a suffix to be used

#### Inheritance

USE flags will not be inherited from the parent unless `inherit_use` is set to true.

FEATURES are inherited by default.

### filters

Several filters are available for cleaning and packing packing layer tarballs.

* `refilter` (true) - Reapply all filters to the final tarball.

#### Path filters

Path filters are used to remove files and directories before packing.

These arguments are set under the `clean_filter_options` dict.

* `man` (true) - Filters man pages.
* `docs` (true) - Filters documentation.
* `include` (true) - Filters headers/includes.
* `charmaps` (true) - Filters charmaps.
* `completions` (true) - Filters shell completions.
* `locales` (false) - Filters locales.
* `vardbpkg` (false) - Filters `/var/db/pkg`.

> `refilter` can be used to reapply filters to the final tarball.

#### Tar filters

Tar filters are used to filter items added to the tarball.

They are set under the `tar_filter_options` dict; any path filter can be used in addition to:

* `whiteouts` (true) - Handles OCI whiteouts. (.wh. files)
* `dev` (true) - Filters character and block devices.

### Profile

The profile can be set using:

* `profile` (default/linux/amd64/23.0) - The profile to use.
* `profile_repos` (gentoo) - The repository source for the profile.

### emerge bools

boolean operators to the `emerge` commad can be set using:

`
[emerge_bools]
verbose = true
with_bdeps = false
`

> Operators which cannot be set =n should be defined in PORTAGE_PLAIN_BOOLS

### Portage Environment Variables

Portage environment variables can be set in the configuration file:

* `use` (set/list) - USE flags to set.
* `features` (set/list) - FEATURES to set.
* `binpkg_format` (gpkg) - The binary package format to use.

> The `use` and `features` variables are sets which can interpret adding and removing flags using `+` and `-` prefixes.

## Mounts

Several components are mounted into the build namespace as read-only bind mounts:

* `bind_system_repos` (true) - mounts the path `system_repos` to `/var/db/repos`.

### seed (sysroot) overlay

A seed must be defined in the top level config. Seeds are used as the lower layer in an overlay which is chrooted into.

This layer will persist between builds, and will not be cleaned unless `clean_seed` is set to true.

When enabled, `clean_seed` recursivedly removes the uppper and work directories of the seed overlay.

### Config overlay

Configuration overrides to be mounted over `/etc/portage` can be specified using:

* `config_overlay` (str) - The name of the configuration overlay to use (from `config_dir`).
* `inherit_config` (false) - Inherit a config root from the seed.

### Build overlay

The build are performed in overlays which are mounted over `/builds` in the namespace, and under `conf_root`/builds on the host.

> `conf_root` is ~/.local/share/genTree by default

The upper_dir is used to build layers between stages, and the mount point is used for the outermost layer.

The build upper and work directories are cleaned before builds unless `clean_build` is set to false.


