import imp


def load_plugin(name, path):
    return imp.load_source(name, path)
