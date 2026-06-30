from _plotly_utils.colors import n_colors

__author__ = "Martina Kopecká"

class QuantitativeColorScale:
    def __init__(self, n: int, start = 'rgb(52, 204, 235)', end = 'rgb(29, 126, 179)'):
        if n == 1:
            self._colors = [start]
        else:
            self._colors =  n_colors(start, end, n, colortype='rgb')

    def get_nth_color(self, i):
        color = self._colors[i]
        color = color[4:-1]
        colors_rgb = list(map(lambda x: round(float(x)), color.split(", ")))

        return f'rgb({colors_rgb[0]}, {colors_rgb[1]}, {colors_rgb[2]})'
