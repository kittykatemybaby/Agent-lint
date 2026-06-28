from setuptools import setup, find_packages

setup(
    name="agent-lint",
    version="0.1.0",
    description="AI Agent safety CLI — predict before you break production",
    author="Kitty Kate",
    author_email="kittykatemybaby@gmail.com",
    url="https://github.com/kittykatemybaby/Agent-lint",
    py_modules=[
        "stop_conditions", "gene_map", "prediction_dataset",
        "cross_audit", "observation_lifecycle",
    ],
    scripts=["agent-lint"],
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Quality Assurance",
    ],
)
