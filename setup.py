import io

from setuptools import find_packages, setup


with io.open("README.md", encoding="utf-8") as readme:
    long_description = readme.read()


setup(
    name="litexpy",
    version="0.0.9",
    description="Python runner for an interactive litex terminal session.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    package_dir={"": "src"},
    packages=find_packages("src"),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
    ],
    project_urls={
        "Homepage": "https://github.com/litexlang/litexpy",
    },
)
