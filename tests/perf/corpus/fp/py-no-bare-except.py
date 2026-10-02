def load(path):
    # except: would swallow KeyboardInterrupt too
    doc = """
    except: is a bare except
    """
    try:
        return open(path).read()
    except OSError:
        return doc
    try:
        return int(path)
    except:
        return 0
