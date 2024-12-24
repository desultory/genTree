# Copyright 2023-2024 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

DISTUTILS_USE_PEP517=setuptools
PYTHON_COMPAT=( python3_{11..13} )

inherit distutils-r1 git-r3

DESCRIPTION="Gentoo rootfs tree generator"
HOMEPAGE="https://github.com/desultory/genTree"
EGIT_REPO_URI="https://github.com/desultory/${PN}"

LICENSE="GPL-2"
SLOT="0"

RDEPEND="
	>=dev-python/zenlib-9999[${PYTHON_USEDEP}]
"


python_install_all() {
	distutils-r1_python_install_all

	# Create /var/lib/genTree
	keepdir /var/lib/genTree

	# Install the default config root
	insinto /var/lib/genTree/config_roots/default
	doins -r config_roots/default/*
}

