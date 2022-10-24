# Release

## PyMeasure package

1. Pull the latest `master` branch
2. `git checkout -b v<version>_release`
3. Update CHANGES.txt with the changelog
4. Push the changes up as a PR
5. Verify that the builds complete
6. Merge the PR
7. Fetch `master`, build and check the source packages
    - `python -m pip install --upgrade build twine`
    - `python -m build`
    - Check the distributions (`twine check dist/*`, version will not yet be correct)
8. Create a git tag in the format "vX.Y.Z"
9. Build final packages and confirm the correct version number is being used
    - `python -m build`
    - Check the distributions (`twine check dist/*`)
10. Create a tagged release on GitHub

## PyPI release
<<<<<<< HEAD

1. Ensure twine is the latest version (`pip install -U twine`)
2. Check the distributions (`twine check dist/*`)
3. Upload the wheel and source distributions to the test server
    - `twine upload --repository-url https://test.pypi.org/legacy/ dist/PyMeasure-<version>-py3-none-any.whl`
    - `twine upload --repository-url https://test.pypi.org/legacy/ dist/PyMeasure-<version>.tar.gz`
4. Verify the test repository: https://test.pypi.org/project/PyMeasure
5. Upload to the real repository (`twine upload dist/PyMeasure-<version>*`)
6. Verify that the package is updated: https://pypi.org/project/PyMeasure

## conda-forge feedstock

1. Release to PyPI first (the feedstock pulls from there)
2. Pull the latest `master` branch
3. `git checkout -b v<version>_release`
4. Download the tarball and determine the sha256 checksum
    - `wget -qO- https://github.com/pymeasure/pymeasure/archive/<version>.tar.gz | sha256sum`
=======

Official guide [here](https://packaging.python.org/en/latest/tutorials/packaging-projects/).

1. Upload the wheel and source distributions to the test server
    - `python -m twine upload --repository testpypi dist/*`
2. Verify the test repository: https://test.pypi.org/project/PyMeasure
3. Confirm that the installation works (best in a separate environment)
    - `python -m pip install --index-url https://test.pypi.org/simple/ --no-deps pymeasure`
4. Upload to the real repository (`twine upload dist/PyMeasure-<version>*`)
5. Verify that the package is updated: https://pypi.org/project/PyMeasure

## conda-forge feedstock

1. Release to PyPI first (the feedstock pulls from there)
2. Pull the latest `master` branch
3. `git checkout -b v<version>_release`
4. Get the SHA256 hash of the PyPI package at https://pypi.org/project/PyMeasure/#files
>>>>>>> 9f50e169fa62bb4bbfa1ab0256045a314bfb6e59
5. Update recipe/meta.yml with the checksum and version number
6. Push the changes up as a PR
7. Verify that the builds complete
8. Merge the PR
