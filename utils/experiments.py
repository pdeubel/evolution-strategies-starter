from es_errors import InvalidTrainingError
from es_utils import validate_config, validate_log, validate_evaluation


class TrainingRun:
    def __init__(self,
                 config_file,
                 log_file,
                 evaluation_file,
                 video_files,
                 model_files,
                 ob_normalization_files,
                 optimizer_files):
        try:
            self.optimizations, self.model_structure, self.config = validate_config(config_file)
        except InvalidTrainingError:
            raise

        self.log = validate_log(log_file)
        self.evaluation = validate_evaluation(evaluation_file)

        if not isinstance(video_files, list):
            self.video_files = []
        else:
            self.video_files = video_files

        if not isinstance(model_files, list):
            self.model_files = []
        else:
            self.model_files = model_files

        if not isinstance(ob_normalization_files, list):
            self.ob_normalization_files = None
        else:
            self.ob_normalization_files = ob_normalization_files

        if not isinstance(optimizer_files, list):
            self.optimizer_files = []
        else:
            self.optimizer_files = optimizer_files

    # def get_training_state(self):
    #
    #     current_model_file, current_optimizer_file, current_ob_normalization_file = None, None, None
    #
    #     if self.model_files is not None:
    #         current_model_file = self.model_files[-1]
    #
    #     if self.current
    #
    #     return self.optimizations, self.model_structure, self.config
    #     pass

    def __init__(self, save_directory, log, config, model_file_paths, evaluation=None, video_file=None):
        self.save_directory = save_directory
        self.log = log
        self.config = config

        if not model_file_paths:
            self.no_models = True
            self.model_file_paths = None
        else:
            self.no_models = False
            self.model_file_paths = [os.path.join(save_directory, model) for model in model_file_paths]

        if evaluation is not None:
            self.no_evaluation = False
            self.evaluation = evaluation
            self.data = self.merge_log_eval()
        else:
            self.no_evaluation = True
            self.evaluation = None
            self.data = None

        if video_file is not None:
            self.no_video = False
        else:
            self.no_video = True
        self.video_file = video_file

        if self.log is None or self.config is None:
            print("This TrainingRun is missing either the log file or the configuration file. It will not "
                  + "work as expected.")

    def merge_log_eval(self):
        if self.log is not None and self.evaluation is not None:
            return self.log.merge(self.evaluation[['Generation', 'Eval_Rew_Mean', 'Eval_Rew_Std', 'Eval_Len_Mean']],
                                  on='Generation')
        return None

    def parse_generation_number(self, model_file_path):
        try:
            number = int(model_file_path.split('snapshot_')[-1].split('.h5')[0])
            return number
        except ValueError:
            return None

    def evaluate(self, force=False, eval_count=5, skip=None, save=False, delete_models=False):
        if not force:
            if self.data is not None:
                return self.data

        if self.no_models:
            print("No models given for that training run, so no new evaluation is possible. You can still plot" +
                  " your data if you have an evaluation.csv or log.csv.")
            return None

        head_row = ['Generation', 'Eval_per_Gen', 'Eval_Rew_Mean', 'Eval_Rew_Std', 'Eval_Len_Mean']

        for i in range(eval_count):
            head_row.append('Rew_' + str(i))
            head_row.append('Len_' + str(i))

        data = []

        results_list = []
        pool = Pool(os.cpu_count())

        for model_file_path in self.model_file_paths[::skip]:
            results = []
            gen = self.parse_generation_number(model_file_path)

            for _ in range(eval_count):
                results.append(pool.apply_async(func=self.run_model, args=(model_file_path,)))
            results_list.append((results, gen))

        for (results, gen) in results_list:
            for i in range(len(results)):
                results[i] = results[i].get()
                if results[i] == [None, None]:
                    print("The provided model file produces non finite numbers. Stopping.")
                    return

            rewards = np.array(results)[:, 0]
            lengths = np.array(results)[:, 1]

            row = [gen,
                   eval_count,
                   np.mean(rewards),
                   np.std(rewards),
                   np.mean(lengths)]

            assert len(rewards) == len(lengths)
            for i in range(len(rewards)):
                row.append(rewards[i])
                row.append(lengths[i])

            data.append(row)

        pool.close()
        pool.join()

        self.evaluation = pd.DataFrame(data, columns=head_row)
        if save:
            self.save_evaluation()
        # Only copy the mean values in the merged data
        self.data = self.merge_log_eval()

        if delete_models:
            self.delete_model_files

        return self.data

    def delete_model_files(self, save_last=False):
        if save_last:
            self.model_file_paths = self.model_file_paths[:-1]
        for model_file_path in self.model_file_paths:
            os.remove(model_file_path)

    def plot_reward_timestep(self):
        if self.data is not None:
            plot(self.data.TimestepsSoFar, 'Timesteps', self.data.Eval_Rew_Mean, 'Cummulative reward')
        else:
            print("You did not evaluate these results. The evaluated mean reward displayed was computed during training"
                  + "and can have missing values!")
            plot(self.log.TimestepsSoFar, 'Timesteps', self.log.EvalGenRewardMean, 'Cummulative reward')

    def save_evaluation(self):
        if self.evaluation is not None:
            self.evaluation.to_csv(os.path.join(self.save_directory, 'evaluation.csv'))

    def visualize(self, force=False):
        if self.no_models:
            # Error message in Experiment
            return None
        if not force:
            if self.video_file is not None:
                return self.video_file

        latest_model = self.model_file_paths[-1]

        with Pool(os.cpu_count()) as pool:
            pool.apply(func=self.run_model, args=(latest_model, True))

        for file in os.listdir(self.save_directory):
            if file.endswith('.mp4'):
                self.video_file = os.path.join(self.save_directory, file)

        return self.video_file

    def run_model(self, model_file_path, record=False):
        env = gym.make(self.config['config']['env_id'])
        env.reset()

        if record:
            env = wrappers.Monitor(env, self.save_directory, force=True)

        model = load_model(model_file_path)

        try:
            rewards, length = rollout_evaluation(env, model)
        except AssertionError:
            # Is thrown when for example ac is a list which has at least one entry with NaN
            return [None, None]

        return [rewards.sum(), length]


class Experiment():
    def __init__(self, config, training_runs):
        self.config = config
        self.training_runs = training_runs
        self.num_training_runs = len(self.training_runs)
        self.mean_data = None
        self.std_data = None

        self.runs_evaluated = True
        for run in self.training_runs:
            if run.no_evaluation:
                self.runs_evaluated = False

        # Every run has already an evaluation, therefore initialize self.mean_data and self.std_data with it
        if self.runs_evaluated is True:
            self.evaluate()

    def evaluate(self, force=False, eval_count=5, skip=None, save=False, delete_models=False):
        data = []
        no_models = False
        if not self.runs_evaluated:
            for training_run in self.training_runs:
                no_models = training_run.no_models
                if no_models is True:
                    break

        if no_models:
            print("The training runs do not provide model files, therefore the experiment cannot be evaluated." +
                  "Please provide at least one .h5 file.")
        else:
            for training_run in self.training_runs:
                d = training_run.evaluate(force, eval_count, skip, save, delete_models)
                if d is None:
                    return
                data.append(d)
            concatenated = pd.concat([d for d in data])
            self.mean_data = concatenated.groupby(by='Generation', level=0).mean()
            self.std_data = concatenated.groupby(by='Generation', level=0).std()

    def visualize(self, force=False):
        for run in self.training_runs:
            self.video_file = run.visualize(force=force)
            if self.video_file is not None:
                break
        if self.video_file is None:
            print("The training runs do not provide model files, therefore the experiment cannot be visualized." +
                  "Please provide at least one .h5 file so a video can be recorded.")
        return self.video_file

    def delete_model_files(self, save_last=False):
        for run in self.training_runs:
            run.delete_model_files(save_last)

    def get_num_training_runs(self):
        return self.num_training_runs

    def get_all_training_runs(self):
        return [run for run in self.training_runs]

    def get_all_logs(self):
        return [run.log for run in self.training_runs]

    def get_all_evaluations(self):
        return [run.evaluation for run in self.training_runs]

    def print_config(self):
        print(json.dumps(self.config, indent=4))

    def plot_reward_timestep(self):
        if self.mean_data is None:
            print("You did not evaluate the results. Please run evaluate() on this experiment. The plotted results"
                  + " are used from the log file.")
            for run in self.training_runs:
                run.plot_reward_timestep()
        else:
            y_std = None
            # If we only have one training run the standard deviation will be NaN across all values and therefore
            # not be plotted. Use standard deviation from the only evaluation we have
            if self.num_training_runs > 1:
                y_std = self.std_data.Eval_Rew_Mean
            plot(self.mean_data.TimestepsSoFar, 'Timesteps',
                 self.mean_data.Eval_Rew_Mean, 'Cummulative reward',
                 y_std)
            print("Displayed is the mean reward of {} different runs over timesteps with different random seeds." +
                  " If there was more than one run, the shaded region is the standard deviation of the mean reward.")

    def plot_reward_generation(self):
        if self.mean_data is None:
            print("You did not evaluate the results. Please run evaluate() on this experiment.")
        else:
            y_std = None
            # If we only have one training run the standard deviation will be NaN across all values and therefore
            # not be plotted. Use standard deviation from the only evaluation we have
            if self.num_training_runs > 1:
                y_std = self.std_data.Eval_Rew_Mean
            plot(self.mean_data.Generation, 'Generation',
                 self.mean_data.Eval_Rew_Mean, 'Cummulative reward',
                 y_std)
            print("Displayed is the mean reward of {} different runs over timesteps with different random seeds." +
                  " If there was more than one run, the shaded region is the standard deviation of the mean reward.")

    def plot_timesteps_timeelapsed(self):
        if self.mean_data is None:
            print("You did not evaluate the results. Please run evaluate() on this experiment.")
        else:
            y_std = None
            # If we only have one training run the standard deviation will be NaN across all values and therefore
            # not be plotted. Use standard deviation from the only evaluation we have
            if self.num_training_runs > 1:
                y_std = self.std_data.TimestepsSoFar
            plot(self.mean_data.TimeElapsed, 'Time elapsed (s)',
                 self.mean_data.TimestepsSoFar, 'Timesteps',
                 y_std)
            print("Displayed is the mean reward of {} different runs over timesteps with different random seeds." +
                  " If there was more than one run, the shaded region is the standard deviation of the mean reward.")