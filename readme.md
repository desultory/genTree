# genTree

genTree generates a filesystem tree in a namespace using portage.

genTree-server serves the package cache and can be used to queue new builds using genTree.

## Usage

`genTree <config file> [--debug, -d]`

ex. `genTree nginx.toml`

### Importing seeds

A seed must be imported before genTree can be used, whis is done with `genTree-import-seed`:

> `genTree-import-seed <system root> <seed name> [conf_root]

* `system root` - The system root to import, can be a stage3 tarball or a directory.
* `seed name` - The seed name to use.
* `conf_root` - Alternate configuration root to use.

> The `conf_root` is `~/.local/share/genTree` by default

ex. `genTree-import-seed stage3.tar.xz stage3-openrc .`

### Updating seeds

Seeds can be updated with `genTree-update-seed <seed name> [alternate update arg string]`.

ex. `genTree-update-seed stage3-openrc`

> By default, "--jobs 4 --update --deep --newuse --changed-use --with-bdeps=y --usepkg=y @world" is used.
> The update string can be defined with `seed_update_args` in the default config.

### Executing commands in a seed

Commands can be execued in a seed using `genTree-exec [--persistent] <seed name> <command>`.

By default, this will execute the command in an overlay, so it only persists in the upper dir. `--persistent` can be used to execute the command directly in the seed root.

### Adding crossdev support

Crossdev support can be added to a seed with `genTree-init-crossdev <seed name> <target-tuple>`.

ex. `genTree-init-crossdev stage3-openrc aarch64-unknown-linux-gnu`

> The target tuple must be a valid crossdev target.

### Removing builds

To remove old build tarballs, use `genTree-clean-builds`.

`~/.local/share/genTree/builds/` is use by default, but an alternate build dir can be passed with the first arg.

> This is equivalent to `rm ~/.local/share/genTree/builds/*.tar`

## Server usage

genTree can serve binpkgs using `aiohttp` with genTree-server.

`genTree-server <seed name> [--debug, -d] [-a --address <address>] [--port <port>] [--crossdev-target -c] [--profile -p] [--build-tag -t]`

ex. `genTree-server stage3-openrc -a 0.0.0.0`

Builds can be added to a queue using `/pkg?pkg=<pkg>` and viewed using `/queue`. 

## Configuration

Example build configuration file:

```
# nginx.toml

# name = "nginx"  # The name is set to the filename without extension by default
# output_file = "nginx.tar"  # The output file is set to the name with a .tar extension by default

# A seed must be defined
seed = "stage3-openrc"

# profile = "default/linux/amd64/23.0"  # Set the profile

bases = ["tini", "gcc"]

packages = ["www-servers/nginx"]
unmerge = ["sys-devel/gcc"]

[env]
use = "nginx"

[clean_filter_options]
charmaps = true  # Delete charmaps before packing

[tar_filter_options]
locales = true # Filter locales when packing
```

* `packages` (list) - The packages to emerge.
* `unmerge` (list) - The packages to unmerge.
* `deplean` (false) - Run depclean --with-bdeps=n after emerging.
* `rebuild` (false) - Force a rebuild of the layer.

### Defaults

The default config is set in `<module_path>/defaults.toml`, and is merged with:

* `/etc/genTree/config.toml`
* `~/.config/genTree/config.toml`

> Values which are set to None will check DEFAULTS for a value.

The following defaults cannot be set:

* `name` - This must be set per build/layer.
* `bases` - ''
* `packages` / `unmerge` - ''
* `whiteouts` / `opaques` - Handled by filters
* `config_file` - Doesn't make sense to have a default (for inheriting)
* `build_tag` - Used for additional override profiles, as a key.
* `parent` - Set by the parent when adding a base.

The following defaults inheritance can be configured:
* `env.features` - Toggled with `inherit_features`
* `env.use` - Toggled with `inherit_use`
* `env.common_flags` - as well as each common flag type, like cflags, cxxflags, etc.
  - When a `crossdev_target` is set, not used unless `crossdev_use_env` is true.
* `crossdev_env` - Environment variables to set for crossdev, same as env.

> The `env` dict is used to set environment variables including INHERITED_CONFIG, ENV_VARS, and DEF_ARGS

```
# ~/.config/genTree/config.toml

seed = "openrc-hardened"
profile = "default/linux/amd64/23.0/no-multilib/hardened"
crossdev_profile = "default/linux/arm64/23.0"

[env]
cpu_flags_x86 = "aes avx avx2 f16c fma3 mmx mmxext pclmul popcnt rdrand sha sse sse2 sse3 sse4_1 sse4_2 sse4a ssse3 vpclmulqdq"
common_flags = "-march=native -flto -O3 -pipe"

[default.openrc-hardened.pi3]
crossdev_target = "aarch64-unknown-linux-gnu"

[default.openrc-hardened.pi3.crossdev_env]
common_flags = "-march=armv8-a+crc -mtune=cortex-a53 -flto -O3 -pipe"

[default.openrc-desktop]
profile = "default/linux/amd64/23.0/desktop"

[default.openrc-desktop-generic]
package_tag = "generic"
profile = "default/linux/amd64/23.0/desktop"

[default.openrc-desktop-generic.env]
common_flags = "-flto -O3 -pipe"

```

### Bases

Bases are configurations used as a base for another config.

Bases layer contents are extracted to the lower_dir of the build layer's overlayfs mount.

> Builtin bases such as `tini`, `glibc`, and `base` can be specified without a suffix to be used

The path to a base file can be specified for custom bases.

#### Inheritance

* `inherit_use` (true) - Inherit USE flags from the parent.
* `inherit_features` (true) - Inherit FEATURES from the parent.
* `inherit_env` (true) - Inherit misc environment variables from the parent.
* `inherit_config` (false) - Inherit the configuration root from the parent.

> `inherit_env` controls inheritance from `DEF_ARGS` (filter options and emerge args).

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

### emerge args

arguments with values can be set like:

```
[emerge_args]
jobs = 4
```


### emerge bools

boolean operators to the `emerge` commad can be set using:

```
[emerge_bools]
verbose = true
with_bdeps = false
```

> Operators which cannot be set =n should be defined in PORTAGE_PLAIN_BOOLS

### Environment Variables

Environment variables can be set using the `env` dict.

The following variables can be used as sets or strings:

* `use` (set) - USE flags to set.
* `features` (set) - FEATURES to set.
* `binpkg_format` (gpkg) - The binary package format to use.
* `cpu_flags_{x86,arm,ppc}` (set) - CPU flags to set.
* `common_flags` (set) - Common flags to set (appended to CFLAGS, CXXFLAGS, etc.)
* `cflags` (str) - CFLAGS to set.
* `cxxflags` (str) - CXXFLAGS to set.
* `fcflags` (str) - FCFLAGS to set.
* `fflags` (str) - FFLAGS to set.

> The `use` and `features` variables are sets which can interpret adding and removing flags using `+` and `-` prefixes.

ex:
```
[env]
use = "-dracut ugrd"  # The same as ["-dracut", "ugrd"]
features = ["test", "-test"]  # Add and remove test (NOOP)
foo_arg = "bar"  # Set the variable foo_arg to bar
common_flags = "-O3 -pipe -march=native -flto"  # Set common flags

```

## Mounts

Several components are mounted into the build namespace as read-only bind mounts:

* `bind_system_repos` (true) - mounts the path `system_repos` to `/var/db/repos`.

### seed (sysroot) overlay

A seed must be defined in the top level config. Seeds are used as the lower layer in an overlay which is chrooted into.

This layer will persist between builds, and will not be cleaned unless `clean_seed` is set to true.

* `clean_seed` (false) - Clean the seed overlay upper dir before building.
* `ephemeral_seed` (false) - Mount the seed overlay on a tmpfs.

### Config overlay

Configuration overrides to be mounted over `/etc/portage` can be specified using:

* `config_overlay` (str) - The name of the configuration overlay to use (from `config_dir`).
* `inherit_config` (false) - Inherit a config root from the seed.

### Build overlay

The build are performed in overlays which are mounted over `/builds` in the namespace, and under `conf_root`/builds on the host.

> `conf_root` is ~/.local/share/genTree by default

The upper_dir is used to build layers between stages, and the mount point is used for the outermost layer.

* `clean_build` (true) - Clean the build overlay before building.
