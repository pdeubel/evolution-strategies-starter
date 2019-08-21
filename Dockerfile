FROM jupyter/base-notebook:latest

# Switch to root user to install packages
USER root

RUN apt-get update
RUN apt-get dist-upgrade -y

# Install base requirements
RUN apt-get install -y git xvfb

# Roboschool Requirements
RUN apt-get install -y libgl1-mesa-dev libharfbuzz0b libpcre3-dev libqt5x11extras5

# Switch back to unprivileged user for python packages. User is defined in base docker image
USER $NB_USER

RUN conda install --quiet --yes \
    'matplotlib' \
    'tensorflow=1.13*' \
    'numpy=1.16*' &&\
    conda clean --yes --all -f && \
    fix-permissions $CONDA_DIR && \
    fix-permissions /home/$NB_USER

# Use pip for packages that cannot be installed with conda
RUN pip install --quiet \
    gym==0.14 \
    roboschool==1.0.48

# $NB_USER == jovyan, docker does not support dynamic substitution in chown
ADD --chown=jovyan:root . work/evolution-strategies/

WORKDIR work/evolution-strategies/

# Run jupyter notebook with a fake display to allow rendering in roboschool TODO github issue reference
CMD ["xvfb-run", "-a", "jupyter", "notebook"]