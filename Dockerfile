FROM ubuntu:bionic

RUN apt-get update
RUN apt-get dist-upgrade -y

# Install Python3 and Redis server
RUN apt-get install -y python3.7 python3-pip redis-server git tmux

# Run Redis server
COPY redis_config/redis_master.conf /redis_master.conf
RUN redis-server redis_master.conf &

# Install Python prerequisites
RUN pip3 install gym roboschool redis click tensorflow numpy

RUN git clone https://github.com/spikingevolution/evolution-strategies.git
RUN cd evolution-strategies/

# Start the Redis Server
RUN scripts/./local_run_redis.sh

# Train the environment provided in the configuration file
CMD ["scripts/./local_run_exp.sh", "configurations/humanoid.json"]