import setuptools

setuptools.setup(
    name='runcible',
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    author='Grayson Head',
    author_email='grayson@graysonhead.net',
    url='https://github.com/graysonhead/runcible',
    packages=setuptools.find_packages(),
    license='GPL V3',
    install_requires=[
        'paramiko>=3.4,<4',
        'paramiko-expect>=0.3.5',
        'colorama>=0.4.6',
        'cryptography>=42.0',
        'pyyaml>=6.0',
        'mergedb>=0.1.1',
        'pyserial>=3.5',
        'VyattaConfParser>=0.5.1'
    ],
    long_description=open('README.md').read(),
    long_description_content_type='text/x-rst',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Telecommunications Industry',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    project_urls={
        'Source': 'https://github.com/graysonhead/runcible',
        'Bug Reports': 'https://github.com/graysonhead/runcible/issues',
        'Documentation': 'https://runcible.readthedocs.io/en/latest/index.html',
        'Gitter': 'https://gitter.im/runcible_project/community'
    },
    python_requires='>=3.5, <4',
    entry_points={
        'console_scripts': [
            'runcible = runcible.__main__:main'
        ]
    }
)
