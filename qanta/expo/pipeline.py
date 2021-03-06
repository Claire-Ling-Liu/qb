import csv

import luigi
from luigi import LocalTarget, Task, ExternalTask, WrapperTask

from qanta.reporting.performance import load_data, load_audit
from qanta.util.io import safe_path
from qanta.util.qdb import QuestionDatabase
from qanta.util.environment import QB_QUESTION_DB
from qanta.util.constants import (PRED_TARGET, META_TARGET, EXPO_BUZZ, EXPO_FINAL, VW_AUDIT,
                                  EXPO_QUESTIONS)


def find_final(lines):
    for l in lines:
        if l.buzz:
            return l.sentence, l.token, l.guess
    return -1, -1, lines[-1].guess


class CreateTestQuestions(Task):
    def output(self):
        return LocalTarget(safe_path(EXPO_QUESTIONS))

    def run(self):
        db = QuestionDatabase(QB_QUESTION_DB)
        questions = db.all_questions()
        with open(safe_path(EXPO_QUESTIONS), 'w', newline='') as f:
            f.write('id,answer,sent,text\n')
            writer = csv.writer(f, delimiter=',')
            for q in questions.values():
                if q.fold != 'test':
                    continue
                max_sent = max(q.text.keys())
                for i in range(max_sent + 1):
                    writer.writerow([q.qnum, q.page, i, q.text[i]])


class Prerequisites(ExternalTask):
    fold = luigi.Parameter()
    weight = luigi.IntParameter()

    def output(self):
        return [LocalTarget(PRED_TARGET.format(self.fold, self.weight)),
                LocalTarget(META_TARGET.format(self.fold, self.weight))]


class GenerateExpo(Task):
    fold = luigi.Parameter()
    weight = luigi.IntParameter()

    def requires(self):
        yield Prerequisites(fold=self.fold, weight=self.weight)

    def output(self):
        return [LocalTarget(EXPO_BUZZ.format(self.fold, self.weight)),
                LocalTarget(EXPO_FINAL.format(self.fold, self.weight))]

    def run(self):
        db = QuestionDatabase(QB_QUESTION_DB)
        data = load_data(PRED_TARGET.format(self.fold, self.weight),
                         META_TARGET.format(self.fold, self.weight), db)
        audit_data = load_audit(VW_AUDIT.format(self.fold, self.weight))
        buzz_file = open(safe_path(EXPO_BUZZ.format(self.fold, self.weight)), 'w', newline='')
        buzz_file.write('question,sentence,word,page,evidence,final,weight\n')
        buzz_writer = csv.writer(buzz_file, delimiter=',')

        final_file = open(safe_path(EXPO_FINAL.format(self.fold, self.weight)), 'w', newline='')
        final_file.write('question,answer\n')
        final_writer = csv.writer(final_file, delimiter=',')

        def format_audit_line(line):
            features = line.split()
            audit_features = []
            for f in features:
                name, fid, value, weight = f.split(':')
                product = float(value) * float(weight)
                audit_features.append('{}:{}'.format(name, product))
            return ' '.join(audit_features)

        for qnum, lines in data:
            final_sentence, final_token, final_guess = find_final(lines)
            if final_sentence == -1 and final_token == -1:
                final_writer.writerow([qnum, final_guess])

            for l in lines:
                i = 0
                is_final = False
                if l.sentence == final_sentence and l.token == final_token:
                    final_writer.writerow([qnum, l.guess])
                    is_final = True

                for g in l.all_guesses:
                    evidence = format_audit_line(
                        audit_data['{}_{}_{}'.format(l.question, l.sentence, l.token)])
                    buzz_writer.writerow([
                        l.question, l.sentence, l.token, g.guess, evidence,
                        int(is_final and g.guess == l.guess), g.score
                    ])
                    i += 1
                    if i > 4:
                        break
        buzz_file.close()
        final_file.close()


class AllExpo(WrapperTask):
    def requires(self):
        yield GenerateExpo(fold='test', weight=16)
        yield CreateTestQuestions()
