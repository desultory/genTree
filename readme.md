# genTree

genTree generates a filesystem tree using portage.

## Usage

`genTree config.toml`

## Configuration


Example configuration file:

```
name = "nginx"
output_file = "nginx.tar"

bases = ["tini"]

use = "nginx"
packages = ["www-servers/nginx"]
unmerge = ["sys-devel/gcc"]

tar_filter_vardbpkg = true
```

### Bases

Bases are configurations used as a base for another config.

When used, that layer is used as the lower_dir for the overlayfs mount.

> Builtin bases such as `tini`, `glibc`, and `base` can be specified without a suffix to be used

### Tar flters

Several filters are available for use when packing layer tarballs:

* `tar_filter_dev` (true) - Filters character and block devices.
* `tar_filter_man` (true) - Filters man pages.
* `tar_filter_docs` (true) - Filters documentation.
* `tar_filter_include` (false) - Filters headers/includes.
* `tar_filter_vardbpkg` (false) - Filters `/var/db/pkg`.

### Portage Environment Variables

Portage environment variables can be set in the configuration file:

* `emerge_log_dir` - The directory to store emerge logs.
* `portage_logdir` - The directory to store portage logs.
* `pkgdir` - The directory used to store binary packages.
* `portage_tmpdir` - The directory used for temporary files.
* `config_root` - The root used for portage configuration.

> `root` it set using the config.name under config.base_build_dir

