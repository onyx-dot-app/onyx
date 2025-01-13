# Search Quality Test Script

This Python script automates the process of running search quality tests for a backend system.

## Features

- Loads configuration from a YAML file
- Sets up Docker environment
- Manages environment variables
- Switches to specified Git branch
- Uploads test documents
- Runs search quality tests
- Cleans up Docker containers (optional)

## Usage

1. Ensure you have the required dependencies installed.
2. Configure the `search_test_config.yaml` file based on the `search_test_config.yaml.template` file.
3. Configure the `.env_eval` file in `deployment/docker_compose` with the correct environment variables.
4. Set up the PYTHONPATH permanently:
   Add the following line to your shell configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):
   ```
   export PYTHONPATH=$PYTHONPATH:/path/to/onyx/backend
   ```
   Replace `/path/to/onyx` with the actual path to your Onyx repository.
   After adding this line, restart your terminal or run `source ~/.bashrc` (or the appropriate config file) to apply the changes.
5. Navigate to Onyx repo:

```
cd path/to/onyx
```

6. Navigate to the answer_quality folder:

```
cd backend/tests/regression/answer_quality
```

7. To launch the evaluation environment, run the launch_eval_env.py script (this step can be skipped if you are running the env outside of docker, just leave "environment_name" blank):

```
python launch_eval_env.py
```

8. Run the file_uploader.py script to upload the zip files located at the path "zipped_documents_file"

```
python file_uploader.py
```

9. Run the run_qa.py script to ask questions from the jsonl located at the path "questions_file". This will hit the "query/answer-with-quote" API endpoint.

```
python run_qa.py
```

Note: All data will be saved even after the containers are shut down. There are instructions below to re-launching docker containers using this data.

If you decide to run multiple UIs at the same time, the ports will increment upwards from 3000 (E.g. http://localhost:3001).

To see which port the desired instance is on, look at the ports on the nginx container by running `docker ps` or using docker desktop.

Docker daemon must be running for this to work.

## Configuration

Edit `search_test_config.yaml` to set:

- output_folder
  - This is the folder where the folders for each test will go
  - These folders will contain the postgres/vespa data as well as the results for each test
- zipped_documents_file
  - The path to the zip file containing the files you'd like to test against
- questions_file
  - The path to the yaml containing the questions you'd like to test with
- commit_sha
  - Set this to the SHA of the commit you want to run the test against
  - You must clear all local changes if you want to use this option
  - Set this to null if you want it to just use the code as is
- clean_up_docker_containers
  - Set this to true to automatically delete all docker containers, networks and volumes after the test
- launch_web_ui
  - Set this to true if you want to use the UI during/after the testing process
- only_state
  - Whether to only run Vespa and Postgres
- only_retrieve_docs
  - Set true to only retrieve documents, not LLM response
  - This is to save on API costs
- use_cloud_gpu
  - Set to true or false depending on if you want to use the remote gpu
  - Only need to set this if use_cloud_gpu is true
- model_server_ip
  - This is the ip of the remote model server
  - Only need to set this if use_cloud_gpu is true
- model_server_port
  - This is the port of the remote model server
  - Only need to set this if use_cloud_gpu is true
- environment_name
  - Use this if you would like to relaunch a previous test instance
  - Input the env_name of the test you'd like to re-launch
  - Leave empty to launch referencing local default network locations
- limit
  - Max number of questions you'd like to ask against the dataset
  - Set to null for no limit
- llm
  - Fill this out according to the normal LLM seeding

## Relaunching From Existing Data

To launch an existing set of containers that has already completed indexing, set the environment_name variable. This will launch the docker containers mounted on the volumes of the indicated env_name and will not automatically index any documents or run any QA.

Once these containers are launched you can run file_uploader.py or run_qa.py (assuming you have run the steps in the Usage section above).

- file_uploader.py will upload and index additional zipped files located at the zipped_documents_file path.
- run_qa.py will ask questions located at the questions_file path against the indexed documents.
