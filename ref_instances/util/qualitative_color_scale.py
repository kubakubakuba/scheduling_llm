from util.color_scale import ColorScale

__author__ = "Martina Kopecká"

class QualitativeColorScale(ColorScale):
    @staticmethod
    def get_color(index: int):
        return '#{}'.format(QualitativeColorScale.get_colors()[index % QualitativeColorScale.size()])

    @staticmethod
    def size():
        return len(QualitativeColorScale.get_colors())

    @staticmethod
    def get_colors():
        # https://sashamaps.net/docs/resources/20-colors/
        return ['e6194b', '3cb44b', '4363d8', 'f58231', '911eb4', '46f0f0', 'f032e6', 'bcf60c', 'fabebe', '008080', 'e6beff', '9a6324', 'fffac8', '800000', 'aaffc3', '808000', 'ffd8b1', '000075', '808080', 'ffffff', '000000', 'ffe119']