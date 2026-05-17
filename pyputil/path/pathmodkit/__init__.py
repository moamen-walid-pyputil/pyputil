#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# exists
from .exists import exists, batch_exists, subexists

# data
from .data import (
    get_text_data,
    read_resource,
    clear_resource_cache,
    get_resource_stream,
)

# extend
from .extend import (
    extend_path,
    extend_path2,
    extend_namespace_path,
)

# gne
from .gne import (
    ExtensionSearchDepth,
    get_native_extensions,
)

# metafile
from .metafile import (
    getmetafilepkg,
    getmetapath,
    getlocation,
    get_all_meta_paths,
    search_metapath
)

# splitter
from .splitter import (
    split_package,
    merge_splits,
    iter_package_files,
    split_by_file_count,
    split_by_size,
    SplitStrategy,
    SplitFileFilter,
)

# remove
from .remove import (
    remove,
    remove_module,
    remove_package,
    remove_pip_packages,
    preview_removal
)

# size
from .size import size


__all__ = [
    # exists
    'exists',
    'batch_exists',
    'subexists',

    # data
    'get_text_data',
    'read_resource',
    'clear_resource_cache',
    'get_resource_stream',

    # extend
    'extend_path',
    'extend_path2',
    'extend_namespace_path',

    # gne
    'ExtensionSearchDepth',
    'get_native_extensions',

    # metafile
    'getmetafilepkg',
    'getmetapath',
    'getlocation',
    'get_all_meta_paths',

    # splitter
    'split_package',
    'merge_splits',
    'iter_package_files',
    'split_by_file_count',
    'split_by_size',
    'SplitStrategy',
    'SplitFileFilter',

    # remove
    'remove',
    'remove_module',
    'remove_package',
    'remove_pip_packages',
    'preview_removal',

    # size
    'size',
]