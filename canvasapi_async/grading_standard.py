from canvasapi_async.canvas_object import CanvasObject


class GradingStandard(CanvasObject):
    def __str__(self):
        return "{} ({})".format(self.title, self.id)
