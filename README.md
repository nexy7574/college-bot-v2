# College Bot V2

A continuation of [LCC-Bot](http://github.com/nexy7574/LCC-Bot.git) for our college discord.

Note that this entire bot is satirical, especially the AI. Views expressed in documents in this repository may not necessarily be
my actual views, with the intention of being satirical (a lot of the time I'm mocking politicians).

## Installing & Running

### Prequisites

Prequisites are:

**Docker**:

(While you *can* run this without docker, the project is heavily optimised for a docker-compose stack.)

* A machine with docker
* A CPU with at least 64 bits, a core, and a clock speed that's at least more than 1Hz. ARM is not preferred however should work.
* At least 256 Megabytes of RAM (mostly for the host OS & docker, though this project is python so do with that what you will)
* I'd allocate at least 5GB of your disk to this process, but really its not needed. The largest consumer will be chrome for `/screenshot`.

**Ollama**:

Ollama is included in the docker compose stack, which enables the `/ollama` command.
If you do not want to use this server, you should omit it from your `config.toml`. Otherwise, unless you're shoving a GPU into your docker container,
you should expect insane CPU usage.

* Over 50 gigabytes disk space (for multiple models)
* A CPU that has at least 4 cores and runs at at least 2GHz (for some semblance of speed)
* 8GB or more RAM
* (Optional) NVIDIA GTX 1060 **or** AMD 6600 or newer (5th generation and older cards do not support ROCM)

**`/screenshot`**:

This command uses chromium & chromedriver (via selenium) to take screenshots of navigated pages.
This command is not suitable to be run on a low-power VPS

* 3GB Free RAM (maybe more for heavy pages)
* 2+ CPU Cores
* 10GB+ disk

### Configuring

All possible configuration options are in `config.example.toml`. Copy this to `config.toml` and edit it, and off you pop.

### Running

`docker-compose.yml` is provided. Use `docker compose up`. The latest image will be built automatically.

To update the docker file, you should do the following steps:

```shell
$ docker compose down
$ git pull
$ docker compose up --build  # --build required to force a rebuild
```
