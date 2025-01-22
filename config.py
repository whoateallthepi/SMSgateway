from configparser import ConfigParser

def config_sms(filename='config.ini', section='sms'):
    # create a parser
    parser = ConfigParser()
    # read config file
    parser.read(filename)

    # get section 
    sms = {}
    if parser.has_section(section):
        params = parser.items(section)
        for param in params:
            sms[param[0]] = param[1]
    else:
        raise Exception('Section {0} not found in the {1} file'.format(section, filename))

    return sms

def config_api(filename='config.ini', section='api'):
    # create a parser
    parser = ConfigParser()
    # read config file
    parser.read(filename)

    # get section 
    api = {}
    if parser.has_section(section):
        params = parser.items(section)
        for param in params:
            api[param[0]] = param[1]
    else:
        raise Exception('Section {0} not found in the {1} file'.format(section, filename))

    return api