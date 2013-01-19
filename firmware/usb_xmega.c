// Minimal USB Stack for ATxmega32a4u and related
// http://nonolithlabs.com
// (C) 2011 Kevin Mehall (Nonolith Labs) <km@kevinmehall.net>
//
// Heavily borrows from LUFA
// Copyright 2011  Dean Camera (dean [at] fourwalledcubicle [dot] com)
//
// Licensed under the terms of the GNU GPLv3+

#define __INCLUDE_FROM_EVENTS_C
#include "usb.h"

uint8_t ep0_buf_in[USB_EP0SIZE];
uint8_t ep0_buf_out[USB_EP0SIZE];
USB_EP_pair_t endpoints[USB_MAXEP+1] __attribute__((aligned(2), section(".usbendpoints")));


volatile uint8_t USB_DeviceState;
volatile uint8_t USB_Device_ConfigurationNumber;

void USB_Init(){
	//uint_reg_t CurrentGlobalInt = GetGlobalInterruptMask();
	//GlobalInterruptDisable();

	NVM.CMD  = NVM_CMD_READ_CALIB_ROW_gc;
	USB.CAL0 = pgm_read_byte(offsetof(NVM_PROD_SIGNATURES_t, USBCAL0));
	NVM.CMD  = NVM_CMD_READ_CALIB_ROW_gc;
	USB.CAL1 = pgm_read_byte(offsetof(NVM_PROD_SIGNATURES_t, USBCAL1));

	//SetGlobalInterruptMask(CurrentGlobalInt);

	USB_ResetInterface();	
}

// configure USB clock divider per 48mhz internal oscillator
void USB_ResetInterface(){

	//if (USB_Options & USB_DEVICE_OPT_LOWSPEED)
	//  CLK.USBCTRL = ((((F_USB / 6000000) - 1) << CLK_USBPSDIV_gp) | CLK_USBSRC_RC32M_gc | CLK_USBSEN_bm);
	//else
	CLK.USBCTRL = ((((F_USB / 48000000) - 1) << CLK_USBPSDIV_gp) | CLK_USBSRC_RC32M_gc | CLK_USBSEN_bm);
	USB.EPPTR = (unsigned) &endpoints;
	USB.ADDR = 0;
	
	endpoints[0].out.STATUS = 0;
	endpoints[0].out.CTRL = USB_EP_TYPE_CONTROL_gc | USB_EP_size_to_gc(USB_EP0SIZE);
	endpoints[0].out.DATAPTR = (unsigned) &ep0_buf_out;
	endpoints[0].in.STATUS = USB_EP_BUSNACK0_bm;
	endpoints[0].in.CTRL = USB_EP_TYPE_CONTROL_gc | USB_EP_size_to_gc(USB_EP0SIZE);
	endpoints[0].in.DATAPTR = (unsigned) &ep0_buf_in;
	
	USB.CTRLA = USB_ENABLE_bm | USB_SPEED_bm | USB_MAXEP;
	
	USB_Attach();
}

void USB_ep0_send_progmem(const uint8_t* addr, uint16_t size){
	uint8_t *buf = ep0_buf_in;
	uint16_t remaining = size;
	NVM.CMD = NVM_CMD_NO_OPERATION_gc;
	while (remaining--){
		*buf++ = pgm_read_byte(addr++);
	}
	USB_ep0_send(size);
}

void USB_Task(){
	if (USB.STATUS & USB_BUSRST_bm){
		USB.STATUS &= ~USB_BUSRST_bm;
		USB_Init();
	}

	if (endpoints[0].out.STATUS & USB_EP_SETUP_bm){
		endpoints[0].out.CTRL |= USB_EP_TOGGLE_bm;
		endpoints[0].in.CTRL |= USB_EP_TOGGLE_bm;
		if (!USB_HandleSetup()){
			endpoints[0].out.CTRL |= USB_EP_STALL_bm;
			endpoints[0].in.CTRL |= USB_EP_STALL_bm; 
		}
		endpoints[0].out.STATUS &= ~(USB_EP_SETUP_bm | USB_EP_BUSNACK0_bm | USB_EP_TRNCOMPL0_bm );
	}else if(endpoints[0].out.STATUS & USB_EP_TRNCOMPL0_bm){
		EVENT_USB_Device_ControlOUT((uint8_t *) ep0_buf_out, endpoints[0].out.CNT);
		endpoints[0].out.STATUS &= ~(USB_EP_TRNCOMPL0_bm | USB_EP_BUSNACK0_bm);
	}
}

// This sets up the following clocking scheme:
// '32mhz internal osc' configured to run at a calibrated 48 MHz 
// USBCLK comes directly from 48 MHz osc, not PLL
// PLL clk src is 8MHz external xtal, div 8, PLL=64MHz
// SYSCLK prescaler for cpuclk is 2, for 32 Mhz clkcpu

void USB_ConfigureClock(){

	// Configure DFLL for 48MHz, calibrated by USB SOF
	// FIXME - bk - perhaps calibrated by internal 32.768 MHz for use without USB.
	OSC.DFLLCTRL = OSC_RC32MCREF_USBSOF_gc;
	NVM.CMD  = NVM_CMD_READ_CALIB_ROW_gc;
	// FIXME - bk - what about CALA?
	DFLLRC32M.CALB = pgm_read_byte(offsetof(NVM_PROD_SIGNATURES_t, USBRCOSC));
	DFLLRC32M.COMP1 = 0x1B; //Xmega AU manual, p41
	DFLLRC32M.COMP2 = 0xB7;
	DFLLRC32M.CTRL = DFLL_ENABLE_bm;
	
	CCP = CCP_IOREG_gc; //Security Signature to modify clock 
	OSC.XOSCCTRL = 0x4B;	// 8MHz XTAL, 16K startup

	CCP = CCP_IOREG_gc; //Security Signature to modify clock 
	//OSC.CTRL = OSC_RC32MEN_bm | OSC_RC2MEN_bm; // enable internal 32MHz oscillator (actually 48MHz)
	OSC.CTRL = OSC_RC32MEN_bm | OSC_RC2MEN_bm | OSC_XOSCEN_bm; // enable external XTAL, internal 32MHz oscillator (actually 48MHz)

	while(!(OSC.STATUS & OSC_RC32MRDY_bm)); // wait for int oscillator ready
	while(!(OSC.STATUS & OSC_XOSCRDY_bm)); // wait for ext  oscillator ready

	// PLL src is 2MHz calibrated OSC
	//OSC.PLLCTRL = OSC_PLLSRC_RC2M_gc | 16; // 2MHz * 16 = 32MHz 
	//OSC.PLLCTRL = OSC_PLLSRC_RC2M_gc | 10; // 2MHz * 10 = 20MHz 
	// PLL src is external XTAL (8MHz)
	OSC.PLLCTRL = OSC_PLLSRC_XOSC_gc | 8; // 8MHz * 8 = 64MHz 

	CCP = CCP_IOREG_gc;
	OSC.CTRL = OSC_RC32MEN_bm | OSC_PLLEN_bm | OSC_RC2MEN_bm | OSC_XOSCEN_bm; // Enable PLL

	while(!(OSC.STATUS & OSC_PLLRDY_bm)); // wait for PLL ready

	CCP = CCP_IOREG_gc; //Security Signature to modify clock 
	CLK.PSCTRL = 0x04; // div by 2
	CCP = CCP_IOREG_gc; //Security Signature to modify clock 
	CLK.CTRL = CLK_SCLKSEL_PLL_gc; // Select PLL as source of clksys
	//CLK.CTRL = CLK_SCLKSEL_PLL_gc; // Select PLL as source of clksys
	//CLK.PSCTRL = 0x00; // No peripheral clock prescaler clkcpu is PLL output
}

void USB_Event_Stub(void)
{

}
