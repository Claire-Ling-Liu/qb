import os
import importlib

import luigi
from luigi import LocalTarget, Task, WrapperTask

from qanta.pipeline.preprocess import Preprocess
from qanta.util import constants as c
from qanta.util import environment as e
from qanta.guesser.util.format_dan import preprocess
from qanta.guesser.util import load_embeddings
from qanta.guesser import dan
from qanta.guesser.classify.learn_classifiers import print_recall_at_n
from qanta.extract_features import create_guesses


class TrainGuesser(Task):
    guesser_module = luigi.Parameter()
    guesser_class = luigi.Parameter()

    def requires(self):
        module = importlib.import_module(self.guesser_module)
        module_class = getattr(module, self.guesser_class)
        return module_class.luigi_dependency()

    def run(self):
        module = importlib.import_module(self.guesser_module)
        module_class = getattr(module, self.guesser_class)
        guesser_instance = module_class()
        guesser_instance.train()
        guesser_path = '{}.{}'.format(self.guesser_module, self.guesser_class)
        guesser_instance.save(guesser_path)

    def output(self):
        guesser_path = '{}.{}'.format(self.guesser_module, self.guesser_class)
        return LocalTarget(os.path.join(c.GUESSER_TARGET_PREFIX, guesser_path))


class AllGuessers(WrapperTask):
    def requires(self):
        for guesser in c.GUESSER_LIST:
            parts = guesser.split('.')
            guesser_module = '.'.join(parts[:-1])
            guesser_class = parts[-1]
            yield TrainGuesser(guesser_module=guesser_module, guesser_class=guesser_class)


class FormatDan(Task):
    def requires(self):
        yield Preprocess()

    def run(self):
        preprocess()

    def output(self):
        return [
            LocalTarget(c.DEEP_VOCAB_TARGET),
            LocalTarget(c.DEEP_TRAIN_TARGET),
            LocalTarget(c.DEEP_TEST_TARGET),
            LocalTarget(c.DEEP_DEV_TARGET),
            LocalTarget(c.DEEP_DEVTEST_TARGET)
        ]


class LoadEmbeddings(Task):
    def requires(self):
        yield FormatDan()

    def run(self):
        load_embeddings.create()

    def output(self):
        return LocalTarget(c.DEEP_WE_TARGET)


class TrainDAN(Task):
    def requires(self):
        yield LoadEmbeddings()

    def run(self):
        dan.train_dan()

    def output(self):
        return LocalTarget(c.DEEP_DAN_PARAMS_TARGET)


class ComputeDANOutput(Task):
    def requires(self):
        yield TrainDAN()

    def run(self):
        dan.compute_classifier_input()

    def output(self):
        return [
            LocalTarget(c.DEEP_DAN_TRAIN_OUTPUT),
            LocalTarget(c.DEEP_DAN_DEV_OUTPUT)
        ]


class TrainClassifier(Task):
    def requires(self):
        yield ComputeDANOutput()

    def run(self):
        dan.train_classifier()

    def output(self):
        return LocalTarget(c.DEEP_DAN_CLASSIFIER_TARGET)


class EvaluateClassifier(luigi.Task):
    def requires(self):
        yield TrainClassifier()

    def run(self):
        print_recall_at_n()
        
    def output(self):
        return LocalTarget(c.EVAL_RES_TARGET)


class AllDAN(WrapperTask):
    def requires(self):
        yield EvaluateClassifier()


class CreateGuesses(Task):
    def requires(self):
        yield AllDAN()

    def output(self):
        return LocalTarget(e.QB_GUESS_DB)

    def run(self):
        create_guesses(e.QB_GUESS_DB)


@CreateGuesses.event_handler(luigi.Event.FAILURE)
def reset_guess_db(task, exception):
    os.remove(e.QB_GUESS_DB)
