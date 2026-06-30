from abc import abstractmethod

__author__ = "Martina Kopecká"

class ColorScale:
    @staticmethod
    @abstractmethod
    def get_color(index: int):
        pass

    @staticmethod
    @abstractmethod
    def get_colors():
        pass

    @staticmethod
    @abstractmethod
    def size():
        pass
