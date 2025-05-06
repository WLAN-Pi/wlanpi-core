from pydantic import Basemodel


class Start(BaseModel):
    channel: int | None = None
    frequency: int | None = None
    interface: str | None = None
    ssid: str | None = None

    # config_file_path: str | None = None
    # files_path: str | None = None

    debug: bool | None = None
    noprep: bool | None = None
    noAP: bool | None = None
    no11r: bool | None = None
    no11ax: bool | None = None
    no11be: bool | None = None
    noprofilertlv: bool | None = None

    wpa3_personal_transition: bool | None = None
    wpa3_personal: bool | None = None
    oui_update: bool | None = None
    no_bpf_filters: bool | None = None
