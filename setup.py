"""Setup of regraph library."""

from setuptools import setup

setup(
    name='ReGraph',
    version='2.0',
    description='Graph rewriting tool',
    author='Eugenia Oshurko',
    license='MIT License',
    packages=[
        'regraph',
        'regraph.neo4j',
        'regraph.neo4j.cypher_utils',
        'regraph.networkx'],
    package_dir={"regraph": "regraph"},
    zip_safe=False,
    install_requires=[
        "matplotlib",
        "networkx",
        "numpy",
        "pyparsing",
        "lrparsing",
        "sympy",
        "greenery",
        "neo4j-driver"
    ]
)
