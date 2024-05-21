import logging

# Set up logger
HANDLER = logging.StreamHandler()
FORMATTER = logging.Formatter('[%(levelname)s] %(filename)s - %(lineno)d - %(message)s')
HANDLER.setFormatter(FORMATTER)

TELLO_LOGGER = logging.getLogger('djitellopy')
TELLO_LOGGER.addHandler(HANDLER)
TELLO_LOGGER.setLevel(logging.DEBUG)

# Use Tello.LOGGER.setLevel(logging.<LEVEL>) in YOUR CODE
# to only receive logs of the desired level and higher
