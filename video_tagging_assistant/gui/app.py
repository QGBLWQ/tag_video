from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    window = PipelineMainWindow(workbook_path=workbook_path)
    window.show()
    return 0
