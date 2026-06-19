from setuptools import find_packages, setup

setup(
    name="overnight-app-maker",
    version="0.1.0",
    description="Autonomous daily task and overnight app maker scaffold for OpenClaw.",
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=["PyYAML>=6.0.2"],
    package_data={
        "overnight_app_maker.board": ["static/*"],
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "overnight-app-maker=overnight_app_maker.cli:main",
        ],
    },
)
